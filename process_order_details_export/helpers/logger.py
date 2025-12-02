import json

def log_process_event(
    supabase_client,
    process_name: str,
    function_name: str,
    step: str,
    status: str,
    message: str,
    user_id: str,
    token: str,
    metadata: dict = None,
    print_prefix: str = ""
):
    try:
        full_msg = f"{print_prefix}{message}" if print_prefix else message
        print(full_msg)

        # Envia direto para o Supabase, sem chamar outra função
        supabase_client.rpc('fn_log_process_event', {
            "p_process_name": process_name,
            "p_function_name": function_name,
            "p_step": step,
            "p_status": status,
            "p_message": message,
            "p_user_id": user_id,
            "p_metadata": metadata or {},
            "token": token
        }).execute()

    except Exception as log_err:
        print(f"⚠️ Falha ao registrar log: {log_err}")

