"""Estimación de tokens del bloque inyectado en el prompt.

No depende de un tokenizer de proveedor: cuenta caracteres / 4, el mismo
orden de magnitud que usan los estimadores de contexto. Sirve para comparar
adaptadores entre sí, no para facturar una API.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)
