import unicodedata
from datetime import datetime

def normalize_key(key: str) -> str:
    """
    Normaliza uma chave para facilitar o mapeamento: minúsculas, sem acento, underscores.
    """
    key = key.lower()
    key = unicodedata.normalize('NFD', key).encode('ascii', 'ignore').decode('utf-8')
    key = key.replace(' ', '_')
    key = ''.join(c for c in key if c.isalnum() or c == '_')
    return key


def parse_bigint(value) -> int:
    """
    Converte valor em inteiro (BIGINT seguro), validando entradas comuns de planilha.
    Suporta int, float e strings como "1.0", "1.234", "1 000", etc.
    """
    if value is None:
        raise ValueError("Valor ausente para campo inteiro")

    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        # Remove espaços, pontos, vírgulas e .0
        cleaned = value.strip().replace('.', '').replace(',', '')
        if cleaned.endswith(".0"):
            cleaned = cleaned[:-2]
        if not cleaned.isdigit():
            raise ValueError(f"Valor inválido para campo inteiro: {value}")
        return int(cleaned)

    raise ValueError(f"Formato não suportado para campo inteiro: {value}")


def parse_float_value(value: str) -> float:
    """Converte string numérica em float, removendo vírgulas."""
    cleaned = value.replace(',', '')
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def parse_date(value: str) -> str | None:
    """Converte string para ISO date (YYYY-MM-DD), retorna None se inválido."""
    try:
        date = datetime.fromisoformat(value)
    except Exception:
        try:
            date = datetime.strptime(value, '%d/%m/%Y')
        except Exception:
            return None
    if date.year == 1970:
        return None
    return date.date().isoformat()


def clean_text_id(value: str) -> str:
    """Remove sufixo '.0' e filtra apenas dígitos, retornando uma string."""
    if value is None:
        return ''
    
    value = str(value).strip()
    if value.endswith('.0'):
        value = value[:-2]

    return ''.join(filter(str.isdigit, value))


def apply_mapping(parsed_data: list[dict], field_mapping: dict) -> dict:
    """
    Aplica mapeamento de campos definindo orders e order_items, parseando valores e eliminando duplicados.
    Segue a estrutura original de TS: mapeia tabelas 'orders', 'suppliers' e 'order_items'.
    """
    header_map = field_mapping['po_header_mapping']

    # Filtra linhas completamente vazias
    filtered_data = [row for row in parsed_data if any(v not in (None, '') for v in row.values())]
    print(f"🔍 parsed_data (após filtro): {len(filtered_data)} linhas válidas")
    if filtered_data:
        normalized_headers = [normalize_key(k) for k in filtered_data[0].keys()]
        print("🔍 Headers normalizados detectados:", normalized_headers)
    else:
        print("🔍 Nenhuma linha válida em parsed_data após filtro.")

    mapped = {
        'orders': [],
        'order_items': []
    }

    for row in filtered_data:
        normalized_row = {normalize_key(k): v for k, v in row.items()}
        order: dict = {}
        item: dict = {}

        for map_entry in header_map:
            column_key = normalize_key(map_entry['file_column_name'].strip())
            value = normalized_row.get(column_key, None)
            if (value is None or value == '') and map_entry['required']:
                raise ValueError(f'Campo obrigatório "{map_entry["file_column_name"]}" ausente ou inválido.')

            _, table, column = map_entry['db_field'].split('.')
            parsed_value = value

            # Ajuste de tipos: datetimes e strings
            if isinstance(value, datetime):
                parsed_value = value.date().isoformat()
            elif isinstance(value, str):
                if column in ['quantity', 'item_number', 'status_id']:
                    parsed_value = parse_bigint(value)
                elif column == 'unit_price':
                    parsed_value = parse_float_value(value)
                elif column in ['due_date', 'current_delivery_date']:
                    parsed_value = parse_date(value)
                elif column == 'order_number':
                    parsed_value = clean_text_id(value)
            
            if table in ('orders', 'suppliers'):
                order[column] = parsed_value
                if column == "order_number":
                    order_number = parsed_value
            elif table == 'order_items':
                item[column] = parsed_value

        # Verifica se order é válido
        is_valid_order = all(order.get(field) not in (None, '') for field in ['order_number', 'external_id'])

        if is_valid_order:
            mapped['orders'].append(order)

            # Verifica se order_item é válido
            is_valid_item = all(item.get(field) not in (None, '') for field in ['item_number', 'product', 'quantity', 'unit_price', 'due_date'])

            if is_valid_item:
                item['order_number'] = order_number
                mapped['order_items'].append(item)

    # Eliminar pedidos duplicados por order_number
    unique_orders = {}
    for order in mapped['orders']:
        key = order.get('order_number')
        if key:
            unique_orders[key] = order
    mapped['orders'] = list(unique_orders.values())

    # Ordenar os arrays
    mapped['orders'].sort(key=lambda x: x.get('order_number', ''))
    mapped['order_items'].sort(key=lambda x: x.get('order_number', ''))

    return mapped
