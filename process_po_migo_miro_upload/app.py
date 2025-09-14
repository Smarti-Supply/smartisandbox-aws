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
                process_name='migo_miro_upload',
                function_name='process_po_migo_miro_upload',
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
                process_name='migo_miro_upload',
                function_name='process_po_migo_miro_upload',
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
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
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


# Processa batches de dados MIGO MIRO
def process_migo_miro_batches(transformed_data, owner_id, bucket_id, name, supabase_client, token):
    """
    Processa os dados transformados em batches de 500 registros
    """
    total_batches = len(list(chunk_array(transformed_data, 500)))
    
    for idx, batch in enumerate(chunk_array(transformed_data, 500), start=1):
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='process_batch',
            status='info',
            message=f"Enviando lote {idx}/{total_batches} com {len(batch)} registros",
            user_id=owner_id,
            token=token,
            metadata={
                "batch_index": idx,
                "total_batches": total_batches,
                "batch_size": len(batch),
                "bucket_id": bucket_id,
                "filename": name
            },
            print_prefix='🔄 '
        )
        
        # Chama a função do Supabase para processar o batch
        safe_rpc_call(
            supabase_client,
            'fn_process_migo_miro_imports',
            {'payload': batch, 'token': token, 'owner_id': owner_id},
            owner_id,
            token,
            success_message=f"Lote {idx}/{total_batches} processado com sucesso! ({len(batch)} registros)",
            error_context=f"Lote {idx} de dados MIGO MIRO",
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
        
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='validate_payload',
            status='success',
            message=f"Payload recebido: arquivo '{name}' no bucket '{bucket_id}'",
            user_id=owner_id,
            token=token,
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='📦 '
        )
        
        if not all([bucket_id, name, owner_id]):
            log_process_event(
                supabase_client,
                process_name='migo_miro_upload',
                function_name='process_po_migo_miro_upload',
                step='validate_payload',
                status='error',
                message='Payload incompleto: bucket_id, name ou owner_id ausente',
                user_id=owner_id if owner_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='❌ '
            )
            raise ValueError('Payload incompleto')

        # 5️⃣ Download
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
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
                process_name='migo_miro_upload',
                function_name='process_po_migo_miro_upload',
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

        # 6️⃣ Parse + transformação para o formato esperado
        t0 = time.monotonic()
        parsed_data = parse_file(file_content)
        transformed_data = apply_mapping(parsed_data)
        duration = round(time.monotonic() - t0, 2)
        
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='parse_and_transform',
            status='success',
            message=f"Parse+transformação levou {duration:.2f}s — {len(transformed_data)} registros transformados",
            user_id=owner_id,
            token=token,
            metadata={
                "bucket_id": bucket_id,
                "filename": name,
                "duration_seconds": duration,
                "total_records": len(transformed_data)
            },
            print_prefix='⏱ '
        )
        del file_content, parsed_data

        # 7️⃣ Processar em batches
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='start_batch_processing',
            status='info',
            message=f"Iniciando processamento em batches de {len(transformed_data)} registros",
            user_id=owner_id,
            token=token,
            metadata={
                "bucket_id": bucket_id,
                "filename": name,
                "total_records": len(transformed_data),
                "batch_size": 500
            },
            print_prefix='🚀 '
        )
        
        # Processa os dados em batches
        process_migo_miro_batches(transformed_data, owner_id, bucket_id, name, supabase_client, token)
        
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='batch_processing_complete',
            status='success',
            message=f"Processamento em batches concluído com sucesso para o arquivo '{name}'",
            user_id=owner_id,
            token=token,
            metadata={"bucket_id": bucket_id, "filename": name, "total_records": len(transformed_data)},
            print_prefix='✅ '
        )
        
        return {
            'statusCode': 200, 
            'headers': {**headers, 'Content-Type': 'application/json'}, 
            'body': json.dumps({
                'success': True, 
                'processed_records': len(transformed_data),
                'total_batches': len(list(chunk_array(transformed_data, 500)))
            })
        }

    except Exception as e:
        log_process_event(
            supabase_client,
            process_name='migo_miro_upload',
            function_name='process_po_migo_miro_upload',
            step='error_handling',
            status='error',
            message=f"Erro na função de processamento: {e}",
            user_id=owner_id if owner_id else 'unknown',
            token=token if token else 'unknown',
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='❌ '
        )
        return {
            'statusCode': 500, 
            'headers': {**headers, 'Content-Type': 'application/json'}, 
            'body': json.dumps({'error': str(e)})
        }

    finally:
        # 8️⃣ Always-remove arquivo do bucket
        if supabase_client and bucket_id and name:
            try:
                bucket = supabase_client.storage.from_(bucket_id)
                remove_res = bucket.remove([name])
                err = remove_res.get('error') if isinstance(remove_res, dict) else getattr(remove_res, 'error', None)
                if err:
                    log_process_event(
                        supabase_client,
                        process_name='migo_miro_upload',
                        function_name='process_po_migo_miro_upload',
                        step='cleanup_file',
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
                        process_name='migo_miro_upload',
                        function_name='process_po_migo_miro_upload',
                        step='cleanup_file',
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
                    process_name='migo_miro_upload',
                    function_name='process_po_migo_miro_upload',
                    step='cleanup_file',
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
                process_name='migo_miro_upload',
                function_name='process_po_migo_miro_upload',
                step='cleanup_file',
                status='skip',
                message="Remoção do arquivo ignorada: supabase_client, bucket_id ou name não definido",
                user_id=owner_id if owner_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='⚠️ '
            )