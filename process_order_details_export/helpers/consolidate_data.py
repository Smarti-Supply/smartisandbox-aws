import json
from typing import List, Dict, Any


def format_array_as_string(array: List[Any], separator: str = "; ") -> str:
    """
    Converte um array em uma string legível, separada por vírgula ou ponto-e-vírgula.
    Garante que caracteres Unicode sejam exibidos corretamente (sem escape).
    
    Args:
        array: Lista de valores a serem formatados
        separator: Separador entre os valores (padrão: "; ")
    
    Returns:
        String formatada com os valores separados
    """
    if not array:
        return ''
    
    # Converter cada item para string e garantir que caracteres Unicode sejam exibidos corretamente
    formatted_items = [str(item) for item in array if item is not None and str(item).strip() != '']
    
    if not formatted_items:
        return ''
    
    return separator.join(formatted_items)


def consolidate_data(
    order_id: int, 
    order: Dict, 
    order_items: List[Dict], 
    observations: List[Dict], 
    followup_tracking: List[Dict],
    order_item_invoices: List[Dict] = None
) -> List[Dict]:
    """
    Consolida dados de order, order_items, observations, followup_tracking e order_item_invoices por numero_item.
    
    Args:
        order_id: ID do pedido
        order: Objeto com dados da tabela orders
        order_items: Lista de objetos da tabela order_items (com campo id e numero_item)
        observations: Lista de observações (cada uma com numero_item, pode ser null)
        followup_tracking: Lista de tracking de follow-ups (cada um com numero_item, pode ser null)
        order_item_invoices: Lista de invoices relacionadas aos order_items (cada uma com numero_item)
    
    Returns:
        Lista de objetos consolidados, um por numero_item
    """
    if order_item_invoices is None:
        order_item_invoices = []
    # Criar dicionário de order_items por numero_item (prioridade) ou id
    # Usar numero_item como chave principal, mas também indexar por id se existir
    order_items_by_id: Dict[int, Dict] = {}
    
    for item in order_items:
        # Priorizar numero_item, depois id_item (novo nome), depois id (nome antigo), depois order_item_id (fallback)
        numero_item = item.get('numero_item')
        db_id = item.get('id_item') or item.get('id')  # Suportar tanto id_item quanto id
        
        # Usar numero_item como chave principal
        if numero_item is not None:
            order_items_by_id[numero_item] = item
        # Se não tiver numero_item mas tiver id_item/id, usar como chave
        elif db_id is not None:
            order_items_by_id[db_id] = item
        # Fallback para order_item_id se existir
        elif item.get('order_item_id') is not None:
            order_items_by_id[item.get('order_item_id')] = item
    
    # Agrupar observations por numero_item
    # Observations com numero_item null são observações do pedido e devem ser associadas a TODOS os itens
    observations_by_item: Dict[int, List[Dict]] = {}
    observations_order_level: List[Dict] = []  # Observations do nível do pedido (numero_item null)
    
    for obs in observations:
        item_id = obs.get('numero_item')  # Mudança: usar numero_item em vez de order_item_id
        if item_id is not None:
            if item_id not in observations_by_item:
                observations_by_item[item_id] = []
            observations_by_item[item_id].append(obs)
        else:
            # Observation do nível do pedido - será associada a todos os itens
            observations_order_level.append(obs)
    
    # Agrupar followup_tracking por numero_item
    followups_by_item: Dict[int, List[Dict]] = {}
    followups_order_level: List[Dict] = []  # Followups do nível do pedido (numero_item null)
    
    for followup in followup_tracking:
        followup_item_id = followup.get('numero_item')  # Mudança: usar numero_item em vez de order_item_id
        if followup_item_id is not None:
            # Verifica se o numero_item existe nos order_items
            if followup_item_id in order_items_by_id:
                item_id = followup_item_id
                if item_id not in followups_by_item:
                    followups_by_item[item_id] = []
                followups_by_item[item_id].append(followup)
            else:
                # Se não encontrar correspondência, incluir em todos os itens (similar a observations)
                followups_order_level.append(followup)
        else:
            # Followup do nível do pedido - será associado a todos os itens
            followups_order_level.append(followup)
    
    # Agrupar order_item_invoices por numero_item
    invoices_by_item: Dict[int, List[Dict]] = {}
    
    for invoice in order_item_invoices:
        item_id = invoice.get('numero_item')
        if item_id is not None:
            if item_id not in invoices_by_item:
                invoices_by_item[item_id] = []
            invoices_by_item[item_id].append(invoice)
    
    # Obter todos os order_item_ids únicos (APENAS de order_items - não criar linhas para observations/followup sem order_item)
    all_item_ids = set(order_items_by_id.keys())
    
    # Se não houver nenhum item, retornar vazio
    if not all_item_ids:
        return []
    
    # Criar linha consolidada para cada order_item_id
    consolidated_rows = []
    
    for item_id in sorted(all_item_ids):
        # Pegar dados do order_item correspondente
        order_item = order_items_by_id.get(item_id, {})
        # Combinar observations do item específico + observations do nível do pedido
        item_observations = observations_by_item.get(item_id, []) + observations_order_level
        # Combinar followups do item específico + followups do nível do pedido
        item_followups = followups_by_item.get(item_id, []) + followups_order_level
        # Pegar invoices do item específico
        item_invoices = invoices_by_item.get(item_id, [])
        
        # Pegar primeira observation para campos únicos
        first_obs = item_observations[0] if item_observations else {}
        
        # Criar objeto consolidado começando com todos os campos do order
        consolidated_row = {}
        
        # Adicionar todos os campos do order (sem prefixo, mantendo nomes originais)
        for key, value in order.items():
            if value is not None:
                consolidated_row[key] = value
        
        # Adicionar id_pedido explicitamente (renomeado de order_id)
        consolidated_row['id_pedido'] = order_id
        
        # Adicionar todos os campos do order_item
        for key, value in order_item.items():
            if value is not None:
                # numero_item já é o nome correto, não precisa renomear
                consolidated_row[key] = value
        
        # Garantir que numero_item existe (renomeado de order_item_id)
        if 'numero_item' not in consolidated_row:
            consolidated_row['numero_item'] = item_id
        
        # Extrair arrays de observations (usando nomes corretos do payload)
        # Tratar strings vazias "" como None também
        user_observations = [
            obs.get('observacao_do_usuario') 
            for obs in item_observations 
            if obs.get('observacao_do_usuario') is not None and obs.get('observacao_do_usuario') != ''
        ]
        supplier_observations = [
            obs.get('observacao_do_fornecedor') 
            for obs in item_observations 
            if obs.get('observacao_do_fornecedor') is not None and obs.get('observacao_do_fornecedor') != ''
        ]
        delivery_dates = [
            obs.get('data_da_entrega') 
            for obs in item_observations 
            if obs.get('data_da_entrega') is not None
        ]
        
        # Extrair arrays de followup_tracking (usando nome correto do payload)
        rule_names = [
            f.get('regras_de_followup') 
            for f in item_followups 
            if f.get('regras_de_followup') is not None and f.get('regras_de_followup') != ''
        ]
        
        # Extrair arrays de order_item_invoices (apenas campos que serão exportados)
        invoice_nfes = [inv.get('numero_nfe') for inv in item_invoices if inv.get('numero_nfe') is not None]
        invoice_datas = [inv.get('data_nfe') for inv in item_invoices if inv.get('data_nfe') is not None]
        invoice_quantidades = [inv.get('quantidade_faturada') for inv in item_invoices if inv.get('quantidade_faturada') is not None]
        invoice_criado_em = [inv.get('criado_em') for inv in item_invoices if inv.get('criado_em') is not None]
        
        # Adicionar campos consolidados com novos nomes em português
        # Usar formatação de string legível em vez de JSON para evitar escape de Unicode
        consolidated_row['observacao do usuario'] = format_array_as_string(user_observations, "; ")
        consolidated_row['observacao do fornecedor'] = format_array_as_string(supplier_observations, "; ")
        consolidated_row['regras de followup'] = format_array_as_string(rule_names, "; ")
        
        # Adicionar campos consolidados de invoices (apenas os que serão exportados)
        consolidated_row['numero_nfe'] = format_array_as_string(invoice_nfes, "; ")
        consolidated_row['data_nfe'] = format_array_as_string(invoice_datas, "; ")
        consolidated_row['quantidade_faturada'] = format_array_as_string(invoice_quantidades, "; ")
        consolidated_row['quantidade_faturada_criado_em'] = format_array_as_string(invoice_criado_em, "; ")
        
        # data_da_entrega: priorizar da observation, senão manter o que já veio do order_item
        if delivery_dates:
            consolidated_row['data_da_entrega'] = delivery_dates[0]
        # Se não veio da observation e não existe no order_item, deixar vazio (já está no order_item se existir)
        
        # Nota: criado_em foi removido de observations, então não incluímos mais esse campo
        
        consolidated_rows.append(consolidated_row)
    
    return consolidated_rows

