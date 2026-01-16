import html
from datetime import datetime
from typing import List, Dict, Any, Optional
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors


def format_date(date_str: Optional[str]) -> str:
    """
    Formata data ISO para formato brasileiro (DD/MM/YYYY).
    
    Args:
        date_str: String de data no formato ISO (YYYY-MM-DD ou YYYY-MM-DDTHH:MM:SS)
    
    Returns:
        String formatada como DD/MM/YYYY ou DD/MM se não tiver ano
    """
    if not date_str:
        return ''
    
    try:
        # Tentar parsear com timezone
        if 'T' in date_str:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
        
        return dt.strftime('%d/%m/%Y')
    except:
        # Se falhar, retornar original
        return date_str


def format_datetime(datetime_str: Optional[str]) -> str:
    """
    Formata datetime ISO para formato brasileiro (DD/MM/YYYY HH:MM).
    
    Args:
        datetime_str: String de datetime no formato ISO
    
    Returns:
        String formatada como DD/MM/YYYY HH:MM
    """
    if not datetime_str:
        return ''
    
    try:
        # Tentar parsear com timezone
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        try:
            # Tentar apenas data
            dt = datetime.strptime(datetime_str, '%Y-%m-%d')
            return dt.strftime('%d/%m/%Y')
        except:
            return datetime_str


def format_user(user_nome: Optional[str], user_email: Optional[str]) -> str:
    """
    Formata nome e email do usuário para exibição.
    
    Args:
        user_nome: Nome do usuário
        user_email: Email do usuário
    
    Returns:
        String formatada como "Nome (email@example.com)" ou apenas nome/email se um estiver faltando
    """
    nome = (user_nome or '').strip()
    email = (user_email or '').strip()
    
    if nome and email:
        return f"{nome} ({email})"
    elif nome:
        return nome
    elif email:
        return email
    else:
        return '-'


def create_timeline_events(
    order: Dict,
    order_items: List[Dict],
    observations: List[Dict],
    followup_tracking: List[Dict],
    followup_logs: List[Dict],
    order_item_invoices: List[Dict]
) -> List[Dict]:
    """
    Cria uma lista cronológica de eventos a partir dos dados do pedido.
    
    Args:
        order: Dados do pedido
        order_items: Lista de itens do pedido
        observations: Lista de observações
        followup_tracking: Lista de follow-ups
        followup_logs: Lista de logs de followups enviados
        order_item_invoices: Lista de faturas
    
    Returns:
        Lista de eventos ordenados por data, cada um com 'date', 'description' e 'user'
    """
    events = []
    
    # Mapear order_items por numero_item para facilitar busca
    items_by_numero = {item.get('numero_item'): item for item in order_items if item.get('numero_item')}
    
    # Adicionar eventos de observações
    # Nota: criado_em foi removido de observations, então usamos fallback para data do pedido
    pedido_criado_em = order.get('pedido_criado_em') or order.get('created_at')
    
    for obs in observations:
        item_id = obs.get('numero_item')
        item_info = items_by_numero.get(item_id) if item_id else None
        item_desc = f"Item {item_id}" if item_id else "Pedido"
        
        # Tentar pegar criado_em de diferentes campos possíveis
        # Se não encontrar, usar data do pedido como fallback
        criado_em = (
            obs.get('criado_em') or 
            obs.get('created_at') or 
            obs.get('data_criacao') or
            pedido_criado_em  # Fallback: usar data do pedido
        )
        observacao_usuario = obs.get('observacao_do_usuario')
        observacao_fornecedor = obs.get('observacao_do_fornecedor')
        
        # Extrair informações do usuário
        usuario_nome = obs.get('usuario_nome')
        usuario_email = obs.get('usuario_email')
        user_formatted = format_user(usuario_nome, usuario_email)
        
        # Formatar data para incluir na descrição
        data_formatada = format_datetime(criado_em) if criado_em else ''
        data_suffix = f" ({data_formatada})" if data_formatada else ''
        
        # Criar eventos apenas se houver observação
        if observacao_usuario:
            events.append({
                'date': criado_em if criado_em else None,
                'description': f"Observação Diligenciador ({item_desc}){data_suffix}: {observacao_usuario}",
                'user': user_formatted
            })
        
        if observacao_fornecedor:
            events.append({
                'date': criado_em if criado_em else None,
                'description': f"Observação Fornecedor ({item_desc}){data_suffix}: {observacao_fornecedor}",
                'user': user_formatted
            })
    
    # Adicionar eventos de followup_tracking
    for followup in followup_tracking:
        item_id = followup.get('numero_item')
        item_info = items_by_numero.get(item_id) if item_id else None
        item_desc = f"Item {item_id}" if item_id else "Pedido"
        
        criado_em = followup.get('criado_em')
        regra = followup.get('regras_de_followup')
        
        # Extrair informações do usuário
        usuario_nome = followup.get('usuario_nome')
        usuario_email = followup.get('usuario_email')
        user_formatted = format_user(usuario_nome, usuario_email)
        
        if regra:
            events.append({
                'date': criado_em,
                'description': f"Status do {item_desc} alterado para \"{regra}\"",
                'user': user_formatted
            })
    
    # Adicionar eventos de followup_logs (logs de followups enviados)
    for log in followup_logs:
        sent_at = log.get('sent_at') or log.get('created_at')
        is_automatic = log.get('is_automatic', False)
        notification_type = log.get('notification_type', 'email')
        supplier_contacts = log.get('supplier_contacts', [])
        user_observations = log.get('user_observations', '')
        sent_by = log.get('sent_by', '')
        rule_name = log.get('rule_name', '')
        
        # Formatar tipo de notificação
        tipo_notificacao = 'Email' if notification_type == 'email' else notification_type.capitalize()
        
        # Formatar contatos do fornecedor
        contatos_str = ', '.join(supplier_contacts) if supplier_contacts else 'N/A'
        
        # Determinar quem enviou
        if is_automatic:
            enviado_por = 'Sistema (automático)'
        elif sent_by:
            enviado_por = f'Usuário ({sent_by})'
        else:
            enviado_por = 'Usuário'
        
        # Montar descrição do evento
        desc_parts = []
        
        # Adicionar rule_name no início se existir
        if rule_name and rule_name.strip():
            desc_parts.append(f"Regra: {rule_name}")
            desc_parts.append("-")
        
        desc_parts.append(f"Followup enviado via {tipo_notificacao}")
        if contatos_str and contatos_str != 'N/A':
            desc_parts.append(f"para {contatos_str}")
        desc_parts.append(f"({enviado_por})")
        if user_observations and user_observations.strip():
            # Limitar tamanho da observação para não ficar muito longo
            obs_short = user_observations[:100] + '...' if len(user_observations) > 100 else user_observations
            desc_parts.append(f"- {obs_short}")
        
        events.append({
            'date': sent_at,
            'description': ' '.join(desc_parts),
            'user': enviado_por
        })
    
    # Adicionar eventos de faturas
    for invoice in order_item_invoices:
        item_id = invoice.get('numero_item')
        item_info = items_by_numero.get(item_id) if item_id else None
        item_desc = f"Item {item_id}" if item_id else "Pedido"
        
        criado_em = invoice.get('criado_em')
        numero_nfe = invoice.get('numero_nfe')
        quantidade = invoice.get('quantidade_faturada')
        data_nfe = invoice.get('data_nfe')
        
        # Extrair informações do usuário
        usuario_nome = invoice.get('usuario_nome')
        usuario_email = invoice.get('usuario_email')
        user_formatted = format_user(usuario_nome, usuario_email)
        
        # Montar descrição da fatura
        desc_parts = [f"{item_desc} - faturado"]
        if quantidade:
            desc_parts.append(f"{quantidade} unidades")
        if numero_nfe:
            desc_parts.append(f"- NF {numero_nfe}")
        if data_nfe:
            desc_parts.append(f"(Data NF: {format_date(data_nfe)})")
        
        events.append({
            'date': criado_em,
            'description': " ".join(desc_parts),
            'user': user_formatted
        })
    
    # Ordenar eventos por data (mais antigo primeiro)
    # Eventos sem data vão para o final
    events.sort(key=lambda x: (x['date'] is None, x['date'] or ''))
    
    return events


def generate_pdf(
    order: Dict,
    order_items: List[Dict],
    observations: List[Dict],
    followup_tracking: List[Dict],
    followup_logs: List[Dict],
    order_item_invoices: List[Dict]
) -> bytes:
    """
    Gera PDF a partir dos dados do pedido usando ReportLab.
    
    Args:
        order: Dados do pedido
        order_items: Lista de itens do pedido
        observations: Lista de observações
        followup_tracking: Lista de follow-ups
        followup_logs: Lista de logs de followups enviados
        order_item_invoices: Lista de faturas
    
    Returns:
        Bytes do arquivo PDF
    """
    # Criar buffer para o PDF
    buffer = BytesIO()
    
    # Criar documento PDF
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    doc.leftMargin = 2*cm
    doc.rightMargin = 2*cm
    doc.topMargin = 2*cm
    doc.bottomMargin = 2*cm
    
    # Estilos
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#000000'),
        spaceAfter=30,
        alignment=1  # Center
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 11
    
    # Conteúdo do PDF
    story = []
    
    # Título
    story.append(Paragraph("Relatório do Pedido", title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Informações do pedido
    numero_pedido = str(order.get('numero_pedido', 'N/A'))
    fornecedor = str(order.get('fornecedor', 'N/A'))
    data_remessa = format_date(order.get('pedido_data_da_remessa'))
    
    # Calcular valor total
    valor_total = sum(
        item.get('preco_total', 0) 
        for item in order_items 
        if isinstance(item.get('preco_total'), (int, float))
    )
    valor_total_str = f"R$ {valor_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    # Adicionar informações
    info_text = f"""
    <b>Número do Pedido:</b> {html.escape(numero_pedido)}<br/>
    <b>Nome do Fornecedor:</b> {html.escape(fornecedor)}<br/>
    <b>Data da Remessa:</b> {data_remessa}<br/>
    <b>Valor Total:</b> {valor_total_str}
    """
    story.append(Paragraph(info_text, normal_style))
    story.append(Spacer(1, 1*cm))
    
    # Criar timeline de eventos
    events = create_timeline_events(order, order_items, observations, followup_tracking, followup_logs, order_item_invoices)
    
    # Tabela de eventos
    if events:
        # Cabeçalho da tabela usando Paragraph para permitir formatação
        table_data = [[
            Paragraph('<b>Data</b>', normal_style), 
            Paragraph('<b>Descrição</b>', normal_style),
            Paragraph('<b>Usuário</b>', normal_style)
        ]]
        
        # Adicionar eventos
        for event in events:
            # Garantir que sempre temos uma data formatada
            event_date = event.get('date')
            if event_date:
                try:
                    date_formatted = format_datetime(event_date)
                    # Se a formatação retornar vazio, usar '-'
                    if not date_formatted or date_formatted.strip() == '':
                        date_formatted = '-'
                except Exception:
                    date_formatted = '-'
            else:
                date_formatted = '-'
            
            description = event.get('description', '')
            # Usar Paragraph para permitir quebra de linha automática
            # Escapar HTML para segurança
            description_escaped = html.escape(description)
            
            # Extrair usuário do evento (com fallback para '-')
            user = event.get('user', '-')
            user_escaped = html.escape(user)
            
            table_data.append([
                Paragraph(date_formatted, normal_style),
                Paragraph(description_escaped, normal_style),
                Paragraph(user_escaped, normal_style)
            ])
    else:
        table_data = [
            [
                Paragraph('<b>Data</b>', normal_style), 
                Paragraph('<b>Descrição</b>', normal_style),
                Paragraph('<b>Usuário</b>', normal_style)
            ],
            [
                Paragraph('-', normal_style), 
                Paragraph('Nenhum evento registrado', normal_style),
                Paragraph('-', normal_style)
            ]
        ]
    
    # Criar tabela com 3 colunas: Data, Descrição, Usuário
    # Ajustar larguras: Data (3.5cm), Descrição (10cm), Usuário (4.5cm)
    table = Table(table_data, colWidths=[3.5*cm, 10*cm, 4.5*cm])
    table.setStyle(TableStyle([
        # Cabeçalho
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E0E0E0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#000000')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        # Bordas
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#000000')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        # Linhas alternadas (opcional)
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
        # Padding das células
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    story.append(table)
    
    # Construir PDF
    doc.build(story)
    
    # Retornar bytes
    buffer.seek(0)
    return buffer.getvalue()

