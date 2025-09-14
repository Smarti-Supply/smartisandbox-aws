import os
import boto3
import json
import time
from supabase import create_client, Client
from helpers.parse_zip import parse_zip
from helpers.cors_headers import cors_headers
from helpers.logger import log_process_event


# Cache de secrets e cliente Supabase para evitar recriação a cada invocação
_cached_secrets: dict = None
_supabase_client: Client = None

def _init_clients():
    """
    Inicializa e retorna o cliente Supabase e o AWS_TOKEN (token interno), com cache em nível de módulo.
    """
    global _cached_secrets, _supabase_client
    try:
        if _cached_secrets is None:
            session = boto3.session.Session()
            sm = session.client(
                service_name='secretsmanager',
                region_name=os.environ.get('AWS_REGION', 'sa-east-1')
            )
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

def process_entries(entries, company_id, supabase_client, owner_id):
    """
    Para cada entrada de PDF extraída do ZIP, busca o pedido e faz upload do PDF no bucket 'po-files'.
    """
    for idx, entry in enumerate(entries, start=1):
        order_id = entry['order_id']
        filename = entry['filename']
        blob = entry['blob']
        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='upload_pdf',
            status='success',
            message=f"Processando {idx}/{len(entries)} — arquivo '{filename}' para pedido {order_id}",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"order_id": order_id, "filename": filename, "index": idx, "total": len(entries)},
            print_prefix='🔄 '
        )

        # 1️⃣ Busca o ID interno do pedido
        resp = supabase_client.table('orders') \
            .select('id') \
            .eq('order_number', order_id) \
            .eq('company_id', company_id) \
            .execute()

        data = resp.data if hasattr(resp, 'data') else resp.get('data')
        err  = getattr(resp, 'error', None) or (resp.get('error') if isinstance(resp, dict) else None)
        if err or not data:
            log_process_event(
                supabase_client,
                process_name='order_files_upload',
                function_name='process_po_files',
                step='upload_pdf',
                status='warning',
                message=f"Pedido não encontrado (order_number={order_id}) — saltando '{filename}'",
                user_id=owner_id,
                token=_cached_secrets['AWS_TOKEN'],
                metadata={"order_id": order_id, "filename": filename, "index": idx, "total": len(entries)},
                print_prefix='⚠️ '
            )
            continue

        order_db_id = data[0]['id']
        path = f"{company_id}/{order_db_id}/{order_id}.pdf"

        # 2️⃣ Faz upload do PDF processado
        upload_res = supabase_client.storage \
            .from_("po-files") \
            .upload(
                path,
                blob,
                {"content-type": "application/pdf", "upsert": "true"}
            )

        upload_err = upload_res.get('error') if isinstance(upload_res, dict) else getattr(upload_res, 'error', None)
        if upload_err:
            log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='upload_pdf',
            status='error',
            message=f"Erro ao subir PDF ({order_id}): {upload_err}",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"order_id": order_id, "filename": filename, "index": idx, "total": len(entries)},
            print_prefix='❌ '
        )
        else:
            log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='upload_pdf',
            status='success',
            message=f"PDF {order_id} vinculado ao pedido {order_db_id} com sucesso.",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"order_id": order_id, "filename": filename, "index": idx, "total": len(entries)},
            print_prefix='✅ '
        )

def lambda_handler(event, context):
    origin = event["headers"].get("origin") if event.get("headers") else None
    headers = cors_headers(origin)
    # 0️⃣ Preflight CORS
    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': 'ok'}

    # Variáveis para finally
    bucket_id = name = owner_id = supabase_client = token = None

    try:
        # 1️⃣ Inicializa Supabase e token
        supabase_client, token = _init_clients()

        # 2️⃣ Autenticação
        headers = event.get('headers', {}) or {}
        if headers.get('internal-token') != token:
            return {
                'statusCode': 401,
                'headers': {**headers, 'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Unauthorized'})
            }

        # 3️⃣ Payload
        raw = json.loads(event.get('body', '{}') or '{}')
        bucket_id = raw.get('bucket_id')
        name      = raw.get('name')
        owner_id  = raw.get('owner_id')

        if not all([bucket_id, name, owner_id]):
            raise ValueError('Payload incompleto')

        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='download_zip',
            status='success',
            message=f"Iniciando processamento do ZIP: {name} no bucket {bucket_id}",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"bucket_id": bucket_id, "zip_filename": name},
            print_prefix='📥 '
        )

        # 4️⃣ Download do ZIP
        download_res = supabase_client.storage.from_(bucket_id).download(name)
        if isinstance(download_res, dict) and download_res.get('error'):
            log_process_event(
                supabase_client,
                process_name='order_files_upload',
                function_name='process_po_files',
                step='download_zip',
                status='error',
                message=f"Erro ao baixar o arquivo ZIP: {download_res['error']}",
                user_id=owner_id,
                token=_cached_secrets['AWS_TOKEN'],
                metadata={"bucket_id": bucket_id, "zip_filename": name},
                print_prefix='❌ '
            )
            raise ValueError(f"Erro ao baixar o arquivo ZIP: {download_res['error']}")

        # file_content é bytes
        file_content = download_res.get('data') if isinstance(download_res, dict) else download_res
        zip_bytes    = file_content if isinstance(file_content, (bytes, bytearray)) else file_content.read()

        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='download_zip',
            status='success',
            message=f"Arquivo ZIP '{name}' baixado com sucesso do bucket '{bucket_id}'",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"bucket_id": bucket_id, "zip_filename": name},
            print_prefix='⬇️ '
        )

        # 5️⃣ Parse do ZIP e extração de PDFs
        t0 = time.monotonic()
        entries = parse_zip(zip_bytes)
        duration = round(time.monotonic() - t0, 2)

        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='parse_zip',
            status='success',
            message=f"Parse do ZIP levou {duration:.2f}s — {len(entries)} arquivos extraídos",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"zip_filename": name, "bucket_id": bucket_id, "duration_seconds": duration, "total_files": len(entries)},
            print_prefix='⏱ '
        )

        # 6️⃣ Enriquecimento: obter company_id do usuário
        resp = supabase_client.table('company_users') \
            .select('company_id') \
            .eq('id', owner_id) \
            .single() \
            .execute()

        if not resp.data:
            log_process_event(
                supabase_client,
                process_name='order_files_upload',
                function_name='process_po_files',
                step='get_company_id',
                status='error',
                message='Erro ao buscar company_id do usuário.',
                user_id=owner_id,
                token=_cached_secrets['AWS_TOKEN'],
                metadata={"owner_id": owner_id},
                print_prefix='❌ '
            )
            raise ValueError('Erro ao buscar company_id do usuário.')
        
        company_id = resp.data['company_id']

        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='get_company_id',
            status='success',
            message=f"company_id '{company_id}' encontrado para o usuário '{owner_id}'",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"owner_id": owner_id, "company_id": company_id},
            print_prefix='🏢 '
        )

        # 7️⃣ Processa cada PDF
        process_entries(entries, company_id, supabase_client, owner_id)

        log_process_event(
            supabase_client,
            process_name='order_files_upload',
            function_name='process_po_files',
            step='process_entries',
            status='success',
            message=f"Processamento finalizado com sucesso para o arquivo '{name}'",
            user_id=owner_id,
            token=_cached_secrets['AWS_TOKEN'],
            metadata={"bucket_id": bucket_id, "filename": name},
            print_prefix='✅ '
        )

        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps({'success': True})
        }

    except Exception as e:
        if supabase_client and owner_id and token:
            log_process_event(
                supabase_client,
                process_name='order_files_upload',
                function_name='process_po_files',
                step='process_entries',
                status='error',
                message=f"Erro na função de processamento: {e}",
                user_id=owner_id,
                token=token,
                metadata={"bucket_id": bucket_id, "filename": name},
                print_prefix='❌ '
            )

        return {
            'statusCode': 500,
            'headers': {**headers, 'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }

    finally:
        # 8️⃣ Always-remove: cleanup do ZIP original
        if supabase_client and bucket_id and name:
            try:
                remove_res = supabase_client.storage.from_(bucket_id).remove([name])
                err = remove_res.get('error') if isinstance(remove_res, dict) else getattr(remove_res, 'error', None)
                if err:
                    log_process_event(
                        supabase_client,
                        process_name='order_files_upload',
                        function_name='process_po_files',
                        step='cleanup_zip',
                        status='error',
                        message=f"Erro ao remover ZIP: {err}",
                        user_id=owner_id,
                        token=token,
                        metadata={"filename": name, "bucket_id": bucket_id},
                        print_prefix='⚠️ '
                    )
                else:
                    log_process_event(
                        supabase_client,
                        process_name='order_files_upload',
                        function_name='process_po_files',
                        step='cleanup_zip',
                        status='success',
                        message=f"ZIP '{name}' removido com sucesso",
                        user_id=owner_id,
                        token=token,
                        metadata={"filename": name, "bucket_id": bucket_id},
                        print_prefix='🧼 '
                    )

            except Exception as rem_e:
                log_process_event(
                    supabase_client,
                    process_name='order_files_upload',
                    function_name='process_po_files',
                    step='cleanup_zip',
                    status='error',
                    message=f"Exceção ao tentar remover ZIP: {rem_e}",
                    user_id=owner_id,
                    token=token,
                    metadata={"filename": name, "bucket_id": bucket_id},
                    print_prefix='❌ '
                )

        else:
            if supabase_client and owner_id and token:
                log_process_event(
                    supabase_client,
                    process_name='order_files_upload',
                    function_name='process_po_files',
                    step='cleanup_zip',
                    status='skip',
                    message="Remoção do ZIP ignorada: variáveis ausentes",
                    user_id=owner_id,
                    token=token,
                    metadata={"filename": name, "bucket_id": bucket_id},
                    print_prefix='⚠️ '
                )
