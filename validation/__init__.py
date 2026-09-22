"""
Camada de validacao: transforma as promessas do projeto em propriedades
verificaveis do pipeline, em vez de comportamento esperado do modelo.

  facts.py     confere cada numero escrito pelo modelo contra o que as tools
               devolveram, e barra metricas que nenhuma tool fornece
  scope.py     decide se a pergunta e do dominio NBA antes de gastar API
  temporal.py  impede que dado velho seja narrado como "ontem" / "hoje"
  schemas.py   contrato de dados de cada tool (faixas, tipos, campos obrigatorios)
"""

from __future__ import annotations

from . import facts, schemas, scope, temporal

__all__ = ["facts", "schemas", "scope", "temporal"]
