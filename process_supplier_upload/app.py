import os
import boto3
import json
import time
from supabase import create_client, Client
from helpers.parse_file import parse_file
from helpers.apply_mapping import apply_mapping
from helpers.chunk_array import chunk_array
from helpers.cors_headers import cors_headers

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
def safe_rpc_call(supabase_client, function_name, params, success_message="", error_context="", raise_exception=False):
    try:
        response = supabase_client.rpc(function_name, params).execute()
        data = response.data
        if isinstance(data, dict) and data.get('error'):
            print(f"❌ Erro ao chamar {function_name} ({error_context}): {data}")
            if raise_exception:
                raise RpcCallError(function_name, 400, data)
            return None
        if success_message:
            print(f"✅ {success_message}")
        return data
    except Exception as e:
        print(f"⚠️ Exceção inesperada ao chamar {function_name} ({error_context}): {e}")
        if raise_exception:
            raise
        return None

# Processa batches de forma inalterada
def process_batches(mapped_data, owner_id, bucket_id, name, supabase_client, token):
    for idx, batch in enumerate(chunk_array(mapped_data['suppliers'], 500), start=1):
        print(f"🔄 Enviando batch {idx} de fornecedores com {len(batch)} registros")
        safe_rpc_call(
            supabase_client,
            'fn_insert_suppliers',
            {'payload': batch, 'token': token, 'owner_id': owner_id},
            success_message=f"Batch {idx} de fornecedores enviado com sucesso!",
            error_context=f"batch {idx} fornecedores",
            raise_exception=True
        )
    for idx, batch in enumerate(chunk_array(mapped_data['supplier_users'], 500), start=1):
        print(f"🔄 Enviando batch {idx} de contatos com {len(batch)} registros")
        safe_rpc_call(
            supabase_client,
            'fn_insert_supplier_users',
            {'payload': batch, 'token': token, 'owner_id': owner_id},
            success_message=f"Batch {idx} de contatos enviado com sucesso!",
            error_context=f"batch {idx} contatos",
            raise_exception=True
        )

# Handler principal com remoção garantida e instrumentada
def lambda_handler(event, context):
    # 1️⃣ Preflight CORS
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': cors_headers(), 'body': 'ok'}

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
            return {'statusCode': 401, 'headers': {**cors_headers(), 'Content-Type': 'application/json'}, 'body': json.dumps({'error': 'Unauthorized'})}

        # 4️⃣ Payload
        raw = json.loads(event.get('body', '{}') or '{}')
        bucket_id = raw.get('bucket_id')
        name = raw.get('name')
        owner_id = raw.get('owner_id')
        field_mapping = raw.get('field_mapping')
        if not all([bucket_id, name, owner_id, field_mapping]):
            raise ValueError('Payload incompleto')

        # 5️⃣ Download
        print(f"📥 Baixando arquivo: {name} do bucket: {bucket_id}")
        download_res = supabase_client.storage.from_(bucket_id).download(name)
        if isinstance(download_res, dict) and download_res.get('error'):
            raise ValueError(f"Erro ao baixar o arquivo: {download_res['error']}")
        file_content = download_res.get('data') if isinstance(download_res, dict) else download_res

        # 6️⃣ Parse+Mapping
        t0 = time.monotonic()
        parsed_data = parse_file(file_content)
        mapped_data = apply_mapping(parsed_data, field_mapping)
        print(f"⏱ Parse+mapping levou {time.monotonic() - t0:.2f}s")
        del file_content, parsed_data

        # 7️⃣ Enriquecimento
        resp = supabase_client.table('company_users').select('company_id').eq('id', owner_id).single().execute()
        if not resp.data:
            raise ValueError('Erro ao buscar company_id do usuário.')
        company_id = resp.data['company_id']
        for lst in ('suppliers', 'supplier_users'):
            mapped_data[lst] = [{**item, 'company_id': company_id} for item in mapped_data[lst]]

        # 8️⃣ Processar batches
        process_batches(mapped_data, owner_id, bucket_id, name, supabase_client, token)

        return {'statusCode': 200, 'headers': {**cors_headers(), 'Content-Type': 'application/json'}, 'body': json.dumps({'success': True})}

    except Exception as e:
        print(f"❌ Erro na função Lambda: {e}")
        return {'statusCode': 500, 'headers': {**cors_headers(), 'Content-Type': 'application/json'}, 'body': json.dumps({'error': str(e)})}

    finally:
        # 9️⃣ Always-remove: instrumentado
        if supabase_client and bucket_id and name:
            try:
                bucket = supabase_client.storage.from_(bucket_id)
                remove_res = bucket.remove([name])
                err = None
                if isinstance(remove_res, dict):
                    err = remove_res.get('error')
                else:
                    err = getattr(remove_res, 'error', None)
                if err:
                    print(f"⚠️ Erro ao remover '{name}': {err}")
                else:
                    print(f"🧼 Arquivo '{name}' removido do bucket '{bucket_id}' com sucesso.")
            except Exception as rem_e:
                print(f"⚠️ Exceção ao tentar remover '{name}' do bucket '{bucket_id}': {rem_e}")
        else:
            print("⚠️ Skip removal: supabase_client, bucket_id ou name não definido")
