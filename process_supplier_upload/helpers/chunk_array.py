from typing import Iterator, Iterable, TypeVar, List
import itertools

T = TypeVar('T')

def chunk_array(iterable: Iterable[T], size: int) -> Iterator[List[T]]:
    """
    Divide um iterable em sub-listas de tamanho `size`, de forma lazy (gera conforme demanda).

    :param iterable: Qualquer iterable de elementos.
    :param size: Tamanho de cada sub-lista. Deve ser > 0.
    :return: Iterator de listas de tamanho até `size`.
    :raises ValueError: se `size` for menor que 1.
    """
    if size < 1:
        raise ValueError(f"Tamanho inválido para chunk_array: {size}. Deve ser >= 1.")
    it = iter(iterable)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk
