# Resultados — efectividad de memoria en OKF-Agente-Viajes

Conversación E2E de 12 turnos (reservas e itinerario), sin LLM externo. El reloj simulado vence la tarifa antes del turno 11. Papers de referencia: MemoryTax (arXiv:2610.29823), MemDev-Bench (arXiv:2610.27524) y Remembering Is Not Enough (arXiv:2610.36652).

Tool Failure Repeat Rate y Stale Data Hallucination Rate: menor es mejor.

| Adaptador | Constraint Compliance Rate (%) | Tool Failure Repeat Rate (%) | Stale Data Hallucination Rate (%) | Raw Detail Recall via M_pas (%) | Tokens Promedio Inyectados en Prompt |
| --- | ---: | ---: | ---: | ---: | ---: |
| FlatSummarizerAdapter | 0 | 100 | 100 | 0 | 122.8 |
| MemGraphRAGLegacyAdapter | 100 | 0 | 100 | 0 | 66.2 |
| MemGraphRAGV2Adapter | 100 | 0 | 0 | 100 | 156.5 |

Lectura: el resumen plano pierde el rechazo de Miami, el HTTP 409 y el dato incidental (compliance 0%, reintento 100%, recall 0%). Legacy conserva ese texto en el grafo, pero no vence la tarifa (alucinación 100%) ni abre M_pas (recall 0%). V2 tipa el rechazo y el fallo, poda la tarifa dentro del PPR y recupera el pasaje crudo (compliance 100%, reintento 0%, alucinación 0%, recall 100%).

