import base64
import json
from datetime import datetime
from helpers.logger import log_process_event


# Template HTML fornecido pelo usuário
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Exportação de dados</title>
  <style>
    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background-color: #DDE6ED;
      margin: 0;
      padding: 0;
      color: #464C53;
      line-height: 1.6;
    }

    @media (max-width: 480px) {
      h2 {
        font-size: 20px !important;
      }

      .alt-link {
        font-size: 12px !important;
      }
    }
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #DDE6ED;">
  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #DDE6ED;">
    <tr>
      <td align="center">
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 800px; background-color: #ffffff; margin: 0 auto; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);">
          <!-- Header -->
          <tr>
            <td align="center" bgcolor="#27374D" style="padding: 20px;">
              <div style="font-size: 28px; font-weight: bold; color: #ffffff;">Smarti<span style="color: #E7295E;">Supply</span></div>
            </td>
          </tr>

          <!-- Main content -->
          <tr>
            <td align="center" style="padding: 30px 20px; font-family: Arial, sans-serif; color: #464C53;">
              <h2 style="font-size: 24px; margin-bottom: 16px; color: #27374D;">Relatório do Pedido</h2>

              <p style="margin: 0 0 20px;">Segue em anexo o relatório em PDF com o histórico completo do pedido.</p>

              <!-- Informações dos Pedidos -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin: 20px auto; background-color: #F3F6F9; border-radius: 6px; border: 1px solid #9DB2BF;">
                <tr>
                  <td style="padding: 20px; color: #464C53; font-family: Arial, sans-serif;">
                    Relatório PDF em anexo
                  </td>
                </tr>
              </table>


          <!-- Footer -->
          <tr>
            <td align="center" bgcolor="#F7F9FA" style="padding: 20px; font-size: 13px; color: #526D82; border-top: 1px solid #9DB2BF;">
              <p style="margin: 0;">© 2025 SmartiSupply. Todos os direitos reservados.</p>
              <p style="margin: 0;"><a href="https://smartirpa.io/supply-chain/" style="color: #526D82; text-decoration: underline;">SmartiSupply</a></p>
              <p style="margin: 0;">Você está recebendo este email como fornecedor parceiro da nossa plataforma.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_email(user_email: str, pdf_bytes: bytes, table_name: str, supabase_client, user_id: str, token: str, process_name: str, order_number: str = None) -> None:
    """
    Envia email via Resend API com arquivo PDF anexado.
    
    Args:
        user_email: Email do destinatário
        pdf_bytes: Arquivo PDF em bytes
        table_name: Nome da tabela (usado no nome do arquivo)
        supabase_client: Cliente Supabase para logs
        user_id: ID do usuário para logs
        token: Token para logs
        process_name: Nome do processo para logs
        order_number: Número do pedido para incluir no assunto 
    """
    try:
        # Gerar nome do arquivo com timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_filename = f"{table_name}_relatorio_{timestamp}.pdf"
        
        # Codificar PDF em base64
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Montar assunto com ou sem order_number
        subject = "Smarti - Relatório do Pedido"
        if order_number:
            subject = f"Smarti - Relatório do Pedido #{order_number}"
        
        # Montar payload
        payload = {
            "from": "SmartiSupply Followup <followup@smartisupply.com.br>",
            "to": [user_email],
            "subject": subject,
            "html": HTML_TEMPLATE,
            "attachments": [
                {
                    "filename": pdf_filename,
                    "content": pdf_base64
                }
            ]
        }
        
        # Headers da API Resend
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer re_gNcQCpe2_NFuXYPXaKtuVRFopioFBJLk4"
        }
        
        # Log início do envio
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='send_email',
            status='info',
            message=f"Iniciando envio de email para '{user_email}' com arquivo '{pdf_filename}'",
            user_id=user_id,
            token=token,
            metadata={
                "user_email": user_email, 
                "pdf_filename": pdf_filename,
                "pdf_size_bytes": len(pdf_bytes)
            },
            print_prefix='📧 '
        )
        
        # Fazer requisição POST para Resend API
        import urllib.request
        import urllib.parse
        
        # Converter payload para JSON
        json_data = json.dumps(payload).encode('utf-8')
        
        # Criar requisição
        req = urllib.request.Request(
            'https://api.resend.com/emails',
            data=json_data,
            headers=headers,
            method='POST'
        )
        
        # Enviar requisição
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            
            if response.status == 200:
                log_process_event(
                    supabase_client,
                    process_name=process_name,
                    function_name='process_order_details_export',
                    step='send_email',
                    status='success',
                    message=f"Email enviado com sucesso para '{user_email}' - ID: {response_data.get('id', 'N/A')}",
                    user_id=user_id,
                    token=token,
                    metadata={
                        "user_email": user_email, 
                        "pdf_filename": pdf_filename,
                        "resend_id": response_data.get('id')
                    },
                    print_prefix='✅ '
                )
            else:
                raise Exception(f"Resend API retornou status {response.status}: {response_data}")
                
    except Exception as e:
        log_process_event(
            supabase_client,
            process_name=process_name,
            function_name='process_order_details_export',
            step='send_email',
            status='error',
            message=f"Erro ao enviar email para '{user_email}': {e}",
            user_id=user_id,
            token=token,
            metadata={
                "user_email": user_email, 
                "pdf_filename": pdf_filename if 'pdf_filename' in locals() else 'unknown'
            },
            print_prefix='❌ '
        )
        raise



