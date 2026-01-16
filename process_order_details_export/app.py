import os
import boto3
import json
import time
from supabase import create_client, Client
from helpers.cors_headers import cors_headers
from helpers.logger import log_process_event
from helpers.consolidate_data import consolidate_data
from helpers.generate_pdf import generate_pdf
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
    order_id = None
    user_id = None
    user_email = None
    supabase_client = None
    token = None
    
    try:
        # 2️⃣ Inicializa clients
        supabase_client, token = _init_clients()
        
        # 3️⃣ Autenticação
        headers_dict = event.get('headers', {})
        if headers_dict.get('internal-token') != token:
            return {'statusCode': 401, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'error': 'Unauthorized'})}
        
        # 4️⃣ Payload
        raw = json.loads(event.get('body', '{}') or '{}')
        # Suportar tanto order_id quanto id_pedido
        order_id = raw.get('order_id') or raw.get('id_pedido')
        order = raw.get('order', {})  # Objeto com dados da tabela orders
        order_items = raw.get('order_items', [])  # Array de objetos da tabela order_items
        observations = raw.get('observations', [])
        followup_tracking = raw.get('followup_tracking', [])
        followup_logs = raw.get('followup_logs', [])  # Array de logs de followups enviados
        order_item_invoices = raw.get('order_item_invoices', [])  # Array de invoices relacionadas
        user_id = raw.get('user_id')
        company_id = raw.get('company_id')
        user_email = raw.get('user_email')
        
        process_name = 'order_details_export'
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='validate_payload',
            status='success',
            message=f"Payload recebido: order_id '{order_id}' para usuário '{user_email}'",
            user_id=user_id,
            token=token,
            metadata={
                "order_id": order_id,
                "user_email": user_email,
                "order_items_count": len(order_items),
                "observations_count": len(observations),
                "followup_tracking_count": len(followup_tracking),
                "followup_logs_count": len(followup_logs),
                "order_item_invoices_count": len(order_item_invoices)
            },
            print_prefix='📦 '
        )
        
        # Validação
        if not all([order_id, order, order_items, user_id, company_id, user_email]):
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_order_details_export',
                step='validate_payload',
                status='error',
                message='Payload incompleto: order_id, order, order_items, user_id, company_id ou user_email ausente',
                user_id=user_id if user_id else 'unknown',
                token=token if token else 'unknown',
                metadata={"order_id": order_id, "user_email": user_email},
                print_prefix='❌ '
            )
            raise ValueError('Payload incompleto')
        
        if not isinstance(order_items, list) or len(order_items) == 0:
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_order_details_export',
                step='validate_payload',
                status='error',
                message='order_items deve ser array não vazio',
                user_id=user_id,
                token=token,
                metadata={"order_id": order_id},
                print_prefix='❌ '
            )
            raise ValueError('order_items deve ser array não vazio')
        
        if not isinstance(observations, list):
            observations = []
        if not isinstance(followup_tracking, list):
            followup_tracking = []
        if not isinstance(followup_logs, list):
            followup_logs = []
        if not isinstance(order_item_invoices, list):
            order_item_invoices = []
        
        # 5️⃣ Consolidar dados
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='consolidate_data',
            status='info',
            message=f"Iniciando consolidação de dados para order_id '{order_id}'",
            user_id=user_id,
            token=token,
            metadata={
                "order_id": order_id,
                "order_items_count": len(order_items),
                "observations_count": len(observations),
                "followup_tracking_count": len(followup_tracking),
                "order_item_invoices_count": len(order_item_invoices)
            },
            print_prefix='🔄 '
        )
        
        t0_consolidate = time.monotonic()
        consolidated_data = consolidate_data(order_id, order, order_items, observations, followup_tracking, order_item_invoices)
        duration_consolidate = round(time.monotonic() - t0_consolidate, 2)
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='consolidate_data',
            status='success',
            message=f"Dados consolidados em {duration_consolidate:.2f}s — {len(consolidated_data)} itens únicos",
            user_id=user_id,
            token=token,
            metadata={
                "order_id": order_id,
                "duration_seconds": duration_consolidate,
                "consolidated_items_count": len(consolidated_data)
            },
            print_prefix='✅ '
        )
        
        # 6️⃣ Gerar PDF
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='generate_pdf',
            status='info',
            message=f"Iniciando geração de PDF para order_id '{order_id}'",
            user_id=user_id,
            token=token,
            metadata={"order_id": order_id},
            print_prefix='📄 '
        )
        
        try:
            t0_pdf = time.monotonic()
            pdf_bytes = generate_pdf(order, order_items, observations, followup_tracking, followup_logs, order_item_invoices)
            duration_pdf = round(time.monotonic() - t0_pdf, 2)
            
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_order_details_export',
                step='generate_pdf',
                status='success',
                message=f"PDF gerado em {duration_pdf:.2f}s — {len(pdf_bytes)} bytes para order_id '{order_id}'",
                user_id=user_id,
                token=token,
                metadata={
                    "order_id": order_id,
                    "duration_seconds": duration_pdf,
                    "file_size_bytes": len(pdf_bytes)
                },
                print_prefix='⏱ '
            )
        except Exception as pdf_error:
            # Se falhar a geração de PDF, logar erro e re-lançar (não podemos continuar sem PDF)
            log_process_event(
                supabase_client,
                process_name=process_name,
                function_name='process_order_details_export',
                step='generate_pdf',
                status='error',
                message=f"Erro ao gerar PDF para order_id '{order_id}': {pdf_error}",
                user_id=user_id,
                token=token,
                metadata={"order_id": order_id, "error": str(pdf_error)},
                print_prefix='❌ '
            )
            raise Exception(f"Erro ao gerar PDF: {pdf_error}") from pdf_error
        
        # 7️⃣ Enviar email
        table_name = f"order_details_{order_id}"
        send_email(user_email, pdf_bytes, table_name, supabase_client, user_id, token, process_name)
        
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='export_complete',
            status='success',
            message=f"Exportação concluída com sucesso para order_id '{order_id}' - email enviado para '{user_email}'",
            user_id=user_id,
            token=token,
            metadata={"order_id": order_id, "user_email": user_email, "total_records": len(consolidated_data)},
            print_prefix='✅ '
        )
        
        return {'statusCode': 200, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'success': True})}
    
    except Exception as e:
        log_process_event(
            supabase_client,
            process_name='order_details_export' if 'process_name' in locals() else 'order_details_export',
            function_name='process_order_details_export',
            step='error_handling',
            status='error',
            message=f"Erro na função de processamento: {e}",
            user_id=user_id if user_id else 'unknown',
            token=token if token else 'unknown',
            metadata={"order_id": order_id, "user_email": user_email},
            print_prefix='❌ '
        )
        return {'statusCode': 500, 'headers': {**headers, 'Content-Type': 'application/json'}, 'body': json.dumps({'error': str(e)})}

