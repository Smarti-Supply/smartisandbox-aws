import os
import boto3
import json
import time
from supabase import create_client, Client
from helpers.cors_headers import cors_headers
from helpers.logger import log_process_event
from helpers.generate_excel import generate_excel
from helpers.send_email import send_email

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

# Handler principal
def lambda_handler(event, context):
    origin = event["headers"].get("origin") if event.get("headers") else None
    headers = cors_headers(origin)
    
    # 1️⃣ Preflight CORS
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': 'ok'}
    
    # Variáveis para uso no try/except
    table_name = None
    user_id = None
    user_email = None
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
        table_name = raw.get('table_name')
        data = raw.get('data')
        user_id = raw.get('user_id')
        company_id = raw.get('company_id')
        user_email = raw.get('user_email')
        
        # Definir process_name dinâmico baseado na tabela
        process_name = f"data_export_{table_name}" if table_name else 'data_export'
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_export',
            step='validate_payload',
            status='success',
            message=f"Payload recebido: tabela '{table_name}' para usuário '{user_email}'",
            user_id=user_id,
            token=token,
            metadata={"table_name": table_name, "user_email": user_email, "total_records": len(data) if data else 0},
            print_prefix='📦 '
        )
        
        # Validação
        if not all([table_name, data, user_id, company_id, user_email]):
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_export',
                step='validate_payload',
                status='error',
                message='Payload incompleto: table_name, data, user_id, company_id ou user_email ausente',
                user_id=user_id if user_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"table_name": table_name, "user_email": user_email},
                print_prefix='❌ '
            )
            raise ValueError('Payload incompleto')
        
        if table_name not in ["suppliers", "order_items"]:
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_export',
                step='validate_payload',
                status='error',
                message=f'Tabela não permitida: {table_name}',
                user_id=user_id,
                token=token,
                metadata={"table_name": table_name},
                print_prefix='❌ '
            )
            raise ValueError(f'Tabela não permitida: {table_name}')
        
        if not isinstance(data, list) or len(data) == 0:
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_export',
                step='validate_payload',
                status='error',
                message='Campo data deve ser array não vazio',
                user_id=user_id,
                token=token,
                metadata={"table_name": table_name, "data_type": type(data).__name__},
                print_prefix='❌ '
            )
            raise ValueError('Campo data deve ser array não vazio')
        
        # 5️⃣ Gerar Excel
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_export',
            step='start_export',
            status='info',
            message=f"Iniciando geração de Excel para tabela '{table_name}' com {len(data)} registros",
            user_id=user_id,
            token=token,
            metadata={"table_name": table_name, "total_records": len(data)},
            print_prefix='🚀 '
        )
        
        t0 = time.monotonic()
        excel_bytes = generate_excel(data, table_name)
        duration = round(time.monotonic() - t0, 2)
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_export',
            step='generate_excel',
            status='success',
            message=f"Excel gerado em {duration:.2f}s — {len(excel_bytes)} bytes para tabela '{table_name}'",
            user_id=user_id,
            token=token,
            metadata={
                "table_name": table_name,
                "duration_seconds": duration,
                "file_size_bytes": len(excel_bytes),
                "total_records": len(data)
            },
            print_prefix='⏱ '
        )
        
        # 6️⃣ Enviar email
        send_email(user_email, excel_bytes, table_name, supabase_client, user_id, token, process_name)
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_export',
            step='export_complete',
            status='success',
            message=f"Exportação concluída com sucesso para tabela '{table_name}' - email enviado para '{user_email}'",
            user_id=user_id,
            token=token,
            metadata={"table_name": table_name, "user_email": user_email, "total_records": len(data)},
            print_prefix='✅ '
        )
        
        return {'statusCode': 200, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'success': True})}
    
    except Exception as e:
        log_process_event(
            supabase_client,
            process_name=process_name if 'process_name' in locals() else 'data_export',
            function_name='process_export',
            step='error_handling',
            status='error',
            message=f"Erro na função de processamento: {e}",
            user_id=user_id if user_id else 'unknown',
            token=token if token else 'unknown',
            metadata={"table_name": table_name, "user_email": user_email},
            print_prefix='❌ '
        )
        return {'statusCode': 500, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'error': str(e)})}
