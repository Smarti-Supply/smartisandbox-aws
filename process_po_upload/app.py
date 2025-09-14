import os
import boto3
import json
import time
from supabase import create_client, Client
from helpers.parse_file import parse_file
from helpers.apply_mapping import apply_mapping
from helpers.chunk_array import chunk_array
from helpers.cors_headers import cors_headers
from helpers.logger import log_process_event

# Cache de secrets e cliente Supabase para evitar recriação a cada invocação
_cached_secrets: dict = None
_supabase_client: Client = None

def _init_clients():
    """
    Inicializa e retorna o cliente Supabase e o AWS_TOKEN, com cache em nível de módulo.
    """
    global _cached_secrets, _supabase_client
    try:
        if _cached_secrets is None:
            session = boto3.session.Session()
            sm = session.client(service_name='secretsmanager', region_name=os.environ.get('AWS_REGION', 'sa-east-1'))
            resp = sm.get_secret_value(SecretId=os.environ['SECRET_NAME'])
            _cached_secrets = json.loads(resp['SecretString'])
        if _supabase_client is None:
            _supabase_client = create_client(
                _cached_secrets['SUPABASE_URL'],
                _cached_secrets['SUPABASE_SERVICE_ROLE_KEY']
            )
        return _supabase_client, _cached_secrets['AWS_TOKEN']
    except Exception as e:
        raise RuntimeError(f"Erro ao inicializar clients: {e}")

# Exceção customizada para chamadas RPC
class RpcCallError(Exception):
    def __init__(self, function_name, status_code, data):
        self.function_name = function_name
        self.status_code = status_code
        self.data = data
        super().__init__(f"Erro na função '{function_name}': Status {status_code} - {data}")


# Helper para chamada segura de RPC
def safe_rpc_call(supabase_client, function_name, params, user_id, token, success_message="", error_context="", raise_exception=False):
    try:
        response = supabase_client.rpc(function_name, params).execute()
        data = response.data
        if isinstance(data, dict) and data.get('error'):
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='rpc_call',
                status='error',
                message=f"Erro ao chamar {function_name} ({error_context}): {data}",
                user_id=user_id,
                token=token,
                metadata={"function_name": function_name, "context": error_context},
                print_prefix='❌ '
            )
            if raise_exception:
                raise RpcCallError(function_name, 400, data)
            return None
        if success_message:
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='rpc_call',
                status='success',
                message=success_message,
                user_id=user_id,
                token=token,
                metadata={"function_name": function_name},
                print_prefix='✅ '
            )            
        return data
    except Exception as e:
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='rpc_call',
            status='error',
            message=f"Exceção inesperada ao chamar {function_name} ({error_context}): {e}",
            user_id=user_id,
            token=token,
            metadata={"function_name": function_name, "context": error_context},
            print_prefix='⚠️ '
        )
        if raise_exception:
            raise
        return None

# Processa batches de pedidos e itens
def process_batches(mapped_data, owner_id, bucket_id, name, supabase_client, token):
    for idx, batch in enumerate(chunk_array(mapped_data['orders'], 500), start=1):
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='process_orders_batch',
            status='info',
            message=f"Enviando lote {idx} de pedidos com {len(batch)} registros",
            user_id=owner_id,
            token=token,
            metadata={"batch_index": idx, "batch_type": "orders", "batch_size": len(batch)},
            print_prefix='🔄 '
        )
        safe_rpc_call(
            supabase_client,
            'fn_insert_orders',
            {'payload': batch, 'token': token, 'owner_id': owner_id},
            owner_id,
            token,
            success_message=f"Lote {idx} de pedidos processado com sucesso!",
            error_context=f"Lote {idx} pedidos",
            raise_exception=True
        )
    for idx, batch in enumerate(chunk_array(mapped_data['order_items'], 500), start=1):
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='process_items_batch',
            status='info',
            message=f"Enviando lote {idx} de itens com {len(batch)} registros",
            user_id=owner_id,
            token=token,
            metadata={"batch_index": idx, "batch_type": "order_items", "batch_size": len(batch)},
            print_prefix='🔄 '
        )
        safe_rpc_call(
            supabase_client,
            'fn_insert_order_items',
            {'payload': batch, 'token': token, 'owner_id': owner_id},
            owner_id,
            token,
            success_message=f"Lote {idx} de itens processado com sucesso!",
            error_context=f"Lote {idx} itens",
            raise_exception=True
        )

# Handler principal
def lambda_handler(event, context):
    origin = event["headers"].get("origin") if event.get("headers") else None
    headers = cors_headers(origin)
    # 1️⃣ Preflight CORS
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': 'ok'}

    # Variáveis para uso no finally
    bucket_id = None
    name = None
    owner_id = None
    supabase_client = None
    token = None

    try:
        # 2️⃣ Inicializa clients
        supabase_client, token = _init_clients()

        # 3️⃣ Autenticação
        headers = event.get('headers', {})
        if headers.get('internal-token') != token:
            return {'statusCode': 401, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'error': 'Unauthorized'})}

        # 4️⃣ Payload
        raw = json.loads(event.get('body', '{}') or '{}')
        bucket_id = raw.get('bucket_id')
        name = raw.get('name')
        owner_id = raw.get('owner_id')
        field_mapping = raw.get('field_mapping')
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='validate_payload',
            status='success',
            message=f"Payload recebido: arquivo '{name}' no bucket '{bucket_id}'",
            user_id=owner_id,
            token=token,
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='📦 '
        )
        if not all([bucket_id, name, owner_id, field_mapping]):
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='validate_payload',
                status='error',
                message='Payload incompleto: bucket_id, name, owner_id ou field_mapping ausente',
                user_id=owner_id if owner_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='❌ '
            )
            raise ValueError('Payload incompleto')

        # 5️⃣ Download
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='download_file',
            status='info',
            message=f"Baixando arquivo '{name}' do bucket '{bucket_id}'",
            user_id=owner_id,
            token=token,
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='📥 '
        )
        download_res = supabase_client.storage.from_(bucket_id).download(name)
        if isinstance(download_res, dict) and download_res.get('error'):
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='download_file',
                status='error',
                message=f"Erro ao baixar o arquivo: {download_res['error']}",
                user_id=owner_id,
                token=token,
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='❌ '
            )
            raise ValueError(f"Erro ao baixar o arquivo: {download_res['error']}")
        file_content = download_res.get('data') if isinstance(download_res, dict) else download_res

        # 6️⃣ Parse+Mapping
        t0 = time.monotonic()
        parsed_data = parse_file(file_content)
        mapped_data = apply_mapping(parsed_data, field_mapping)
        duration = round(time.monotonic() - t0, 2)
        total_orders = len(mapped_data.get("orders", []))
        total_items = len(mapped_data.get("order_items", []))
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='parse_and_map',
            status='success',
            message=f"Parse+mapping levou {duration:.2f}s — {total_orders} ordens, {total_items} itens",
            user_id=owner_id,
            token=token,
            metadata={
                "bucket_id": bucket_id,
                "filename": name,
                "duration_seconds": duration,
                "total_orders": total_orders,
                "total_order_items": total_items
            },
            print_prefix='⏱ '
        )
        del file_content, parsed_data

        # 7️⃣ Enriquecimento: company_id
        resp = supabase_client.table('company_users').select('company_id').eq('id', owner_id).single().execute()
        if not resp.data:
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='enrich_company_id',
                status='error',
                message='Erro ao buscar company_id do usuário.',
                user_id=owner_id,
                token=token,
                metadata={"owner_id": owner_id},
                print_prefix='❌ '
            )
            raise ValueError('Erro ao buscar company_id do usuário.')
        company_id = resp.data['company_id']
        for lst in ('orders', 'order_items'):
            mapped_data[lst] = [{**item, 'company_id': company_id} for item in mapped_data[lst]]

        # 8️⃣ Processar batches de pedidos e itens
        process_batches(mapped_data, owner_id, bucket_id, name, supabase_client, token)
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='process_batches',
            status='success',
            message=f"Lotes de pedidos e itens processados com sucesso para o arquivo '{name}'",
            user_id=owner_id,
            token=token,
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='✅ '
        )
        return {'statusCode': 200, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'success': True})}

    except Exception as e:
        log_process_event(
            supabase_client,
            process_name='orders_upload',
            function_name='process_po_upload',
            step='process_batches',
            status='error',
            message=f"Erro na função de processamento: {e}",
            user_id=owner_id if owner_id else 'unknown',
            token=token if token else 'unknown',
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='❌ '
        )
        return {'statusCode': 500, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'error': str(e)})}

    finally:
        # 9️⃣ Always-remove arquivo do bucket
        if supabase_client and bucket_id and name:
            try:
                bucket = supabase_client.storage.from_(bucket_id)
                remove_res = bucket.remove([name])
                err = remove_res.get('error') if isinstance(remove_res, dict) else getattr(remove_res, 'error', None)
                if err:
                    log_process_event(
                        supabase_client,
                        process_name='orders_upload',
                        function_name='process_po_upload',
                        step='cleanup_zip',
                        status='error',
                        message=f"Erro ao remover '{name}' do bucket '{bucket_id}': {err}",
                        user_id=owner_id if owner_id else 'unknown',
                        token=token if token else 'unknown',
                        metadata={"bucket_id": bucket_id, "filename": name},
                        print_prefix='⚠️ '
                    )
                else:
                    log_process_event(
                        supabase_client,
                        process_name='orders_upload',
                        function_name='process_po_upload',
                        step='cleanup_zip',
                        status='success',
                        message=f"Arquivo '{name}' removido do bucket '{bucket_id}' com sucesso.",
                        user_id=owner_id if owner_id else 'unknown',
                        token=token if token else 'unknown',
                        metadata={"bucket_id": bucket_id, "filename": name},
                        print_prefix='🧼 '
                    )
            except Exception as rem_e:
                log_process_event(
                    supabase_client,
                    process_name='orders_upload',
                    function_name='process_po_upload',
                    step='cleanup_zip',
                    status='error',
                    message=f"Exceção ao tentar remover '{name}' do bucket '{bucket_id}': {rem_e}",
                    user_id=owner_id if owner_id else 'unknown',
                    token=token if token else 'unknown',
                    metadata={"bucket_id": bucket_id, "filename": name},
                    print_prefix='❌ '
                )
        else:
            log_process_event(
                supabase_client,
                process_name='orders_upload',
                function_name='process_po_upload',
                step='cleanup_zip',
                status='skip',
                message="Remoção do arquivo ignorada: supabase_client, bucket_id ou name não definido",
                user_id=owner_id if owner_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='⚠️ '
            )
