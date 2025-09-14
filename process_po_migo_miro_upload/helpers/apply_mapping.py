import unicodedata
from datetime import datetime
from typing import List, Dict, Any, Optional

def normalize_key(key: str) -> str:
    """Normaliza uma chave para facilitar o mapeamento: minúsculas, sem acento, underscores."""
    key = key.lower()
    key = unicodedata.normalize('NFD', key).encode('ascii', 'ignore').decode('utf-8')
    key = key.replace(' ', '_')
    key = ''.join(c for c in key if c.isalnum() or c == '_')
    return key


def parse_date(value: Any) -> Optional[str]:
    """
    Converte uma string de data para o formato YYYY-MM-DD.
    Aceita os formatos: MM/DD/YYYY, M/D/YYYY, YYYY-MM-DD
    Retorna None se o valor for inválido ou vazio.
    """
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None

    # Pega apenas a parte da data caso venha algo como '7/10/2023 00:00:00'
    if ' ' in txt:
        txt = txt.split(' ')[0]

    # Lista de formatos suportados
    date_formats = ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"]
    
    for date_format in date_formats:
        try:
            dt = datetime.strptime(txt, date_format)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    print(f"⚠️ Erro ao parsear data '{txt}': formato não reconhecido")
    return None


def clean_text_id(value: str) -> str:
    """Remove sufixo '.0' e filtra apenas dígitos, retornando uma string."""
    if value is None:
        return ''
    
    value = str(value).strip()
    if value.endswith('.0'):
        value = value[:-2]

    return ''.join(filter(str.isdigit, value))


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


def apply_mapping(parsed_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transforma os dados parseados do Excel (por posição) no formato achatado esperado pela função fn_process_migo_miro_imports:

    Mapeia os dados pela posição das colunas, assumindo layout fixo.
    Índices:
        0 - Número PC (order_number)
        1 - Item PC (item_number)
        2 - Dt. Recebimento
        3 - Data Fatura
        4 - Data Pagto.
    
    Exemplo de saída:
    [
        {
            "numero_pc": 4501522732,
            "itmpc": 1,
            "dt_recebimento": "2023-04-10",
            "data_fatura": null,
            "data_pagto": null
        }
    ]
    """
    flattened_result = []

    for row in parsed_data:
        values = list(row.values())

        if len(values) < 5:
            print(f"⚠️ Linha incompleta ignorada: {row}")
            continue

        try:
            numero_pc = clean_text_id(values[0])
            itmpc = parse_bigint(values[1])
            dt_recebimento = parse_date(values[2])
            data_fatura = parse_date(values[3])
            data_pagto = parse_date(values[4])
        except (ValueError, TypeError) as e:
            print(f"⚠️ Erro ao processar linha: {row} → {e}")
            continue

        flattened_result.append({
            "numero_pc": numero_pc,
            "itmpc": itmpc,
            "dt_recebimento": dt_recebimento,
            "data_fatura": data_fatura,
            "data_pagto": data_pagto
        })

    print(f"✅ Mapping concluído: {len(flattened_result)} registros flatten prontos para envio ao Supabase.")
    return flattened_result