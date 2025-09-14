import openpyxl
import unicodedata
from io import BytesIO

def normalize_key(key: str) -> str:
    """
    Normaliza o nome das colunas: minúsculas, sem acentos, sem espaços.
    """
    key = key.lower()
    key = unicodedata.normalize('NFD', key).encode('ascii', 'ignore').decode('utf-8')  # remove acentos
    key = key.replace(' ', '_')  # substitui espaços por underscores
    key = ''.join(c for c in key if c.isalnum() or c == '_')  # mantém apenas letras, números e underscores
    return key

def parse_file(file_blob: bytes) -> list:
    """
    Parseia um arquivo .xlsx (Excel) e retorna os dados como lista de dicionários
    com colunas normalizadas, utilizando modo de leitura 'read_only' para reduzir
    uso de memória.

    :param file_blob: Blob/bytes recebido do Supabase Storage.
    :return: Lista de objetos (dict) com os dados da primeira aba.
    """
    # Carrega em modo streaming, sem carregar tudo em memória
    workbook = openpyxl.load_workbook(BytesIO(file_blob), data_only=True, read_only=True)
    sheet = workbook.active

    # Iterador de linhas
    rows = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration:
        return []

    headers = [normalize_key(str(cell) if cell is not None else '') for cell in header_row]

    data = []
    for row in rows:
        # Ignora linhas totalmente vazias (inclui strings só com espaços)
        if all(
            cell is None or (isinstance(cell, str) and cell.strip() == '')
            for cell in row
        ):
            continue

        item = {header: cell for header, cell in zip(headers, row)}
        data.append(item)

    return data