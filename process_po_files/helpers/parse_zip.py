import zipfile
import io
import os
import re
from typing import List, Dict, Any, Union


def parse_zip(zip_file: Union[bytes, bytearray, io.BytesIO]) -> List[Dict[str, Any]]:
    """
    Extrai arquivos PDF de um ZIP e retorna uma lista de dicionários contendo:
      - order_id: derivado do nome do arquivo (sem extensão e sem espaços)
      - filename: nome original do arquivo dentro do ZIP
      - blob: conteúdo do PDF em bytes
    """
    entries: List[Dict[str, Any]] = []

    # Abre o ZIP a partir dos bytes
    with zipfile.ZipFile(io.BytesIO(zip_file)) as z:
        for info in z.infolist():
            # Ignora diretórios e arquivos que não sejam PDF
            if info.is_dir() or not info.filename.lower().endswith('.pdf'):
                continue

            filename = info.filename
            # Extrai apenas o nome do arquivo (sem o diretório) e remove a extensão
            basename = os.path.basename(filename)
            raw_order_id = basename[:-4].strip()
            # Remove espaços internos do order_id
            order_id = re.sub(r"\s+", "", raw_order_id)

            # Lê o conteúdo do PDF como bytes
            blob = z.read(info)

            entries.append({
                'order_id': order_id,
                'filename': filename,
                'blob': blob
            })

    return entries
