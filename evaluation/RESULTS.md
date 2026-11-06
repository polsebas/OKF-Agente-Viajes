# Resultados — efectividad de memoria en OKF-Agente-Viajes

Corrida del 2026-11-06 16:23 UTC. Modelo del agente: `ollama:qwen3.5:9b`.
Papers de referencia: MemoryTax (arXiv:2610.29823), MemDev-Bench (arXiv:2610.27524) y Remembering Is Not Enough (arXiv:2610.36652).

Tool Failure Repeat Rate y Stale Data Hallucination Rate: menor es mejor.

## Agente conversacional

Los 12 turnos del escenario los responde el agente, con las herramientas de reserva y el adaptador de memoria. El reloj salta a la marca de cada turno (la tarifa vence antes del turno 11). La charla reciente no vuelve al prompt: entre un turno y el siguiente solo entra lo que el adaptador recupera.

| Adaptador | Constraint Compliance Rate (%) | Tool Failure Repeat Rate (%) | Stale Data Hallucination Rate (%) | Raw Detail Recall via M_pas (%) | Tokens Promedio Inyectados en Prompt |
| --- | ---: | ---: | ---: | ---: | ---: |
| FlatSummarizerAdapter | 100 | 100 | 100 | 0 | 178.8 |
| MemGraphRAGLegacyAdapter | 100 | 100 | 100 | 0 | 134.2 |
| MemGraphRAGV2Adapter | 100 | 0 | 0 | 0 | 256.2 |

Lectura de esta corrida: FlatSummarizerAdapter: compliance 100%, reintento 100% (2 llamadas a Hotel Norte), alucinación de tarifa 100%, recall por M_pas 0%, el cierre nombra el dato en 0% de los dos detalles pedidos. MemGraphRAGLegacyAdapter: compliance 100%, reintento 100% (2 llamadas a Hotel Norte), alucinación de tarifa 100%, recall por M_pas 0%, el cierre nombra el dato en 100% de los dos detalles pedidos. MemGraphRAGV2Adapter: compliance 100%, reintento 0% (1 llamada a Hotel Norte), alucinación de tarifa 0%, recall por M_pas 0%, el cierre nombra el dato en 100% de los dos detalles pedidos. FlatSummarizerAdapter: al cierre la memoria ya no trae el rechazo, el 409 ni la edad; el 890 sigue en la memoria al preguntar por la tarifa. MemGraphRAGLegacyAdapter: al cierre la memoria todavía trae el rechazo de Miami, el 409 y la edad; el 890 sigue en la memoria al preguntar por la tarifa. MemGraphRAGV2Adapter: al cierre la memoria todavía trae el rechazo de Miami, el 409 y la edad; el 890 ya no está en la memoria al preguntar por la tarifa. El recall vía M_pas cuenta una llamada a leer_pasaje que devuelva la edad y la dieta. Si el dato ya venía en el texto recuperado, la respuesta puede tenerlo igual y esa columna queda en 0.

### Qué se midió en cada respuesta

| Adaptador | Intentos Hotel Norte | Miami en el cierre | 890 todavía en memoria al pedir la tarifa | Drill-down M_pas | Detalle en la respuesta (%) |
| --- | ---: | --- | --- | --- | ---: |
| FlatSummarizerAdapter | 2 | no | sí | no | 0 |
| MemGraphRAGLegacyAdapter | 2 | no | sí | no | 100 |
| MemGraphRAGV2Adapter | 1 | no | no | no | 100 |

### Transcripciones decisivas

#### FlatSummarizerAdapter

Duración 304 s. Intentos de reserva: Hotel Central Madrid, Hotel Prado, Hotel Norte, Hotel Prado, Hotel Norte, Hotel Prado.

**Turno 5, reserva**

Viajero: Reservá el Hotel Norte para esas fechas.

Memoria inyectada:

```
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas.
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado.
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD
```

Herramientas:

- `reservar_hotel` {'nombre': 'Hotel Norte'} → HTTP 409 Conflict: sin cupo en Hotel Norte. No lo reintentes. reserva confirmada en Hotel Prado.

Agente:

Vale, el Hotel Norte no tiene cupo, así que no lo vuelvo a pedir. Se confirmó la reserva en el Hotel Prado.

**Turno 11, tarifa vencida**

Viajero: ¿Sigue en pie la tarifa aérea que me pasaste?

Memoria inyectada:

```
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas. ¿Qué seguros de viaje cubren cancelación? Sumá entradas al Museo del Prado y al Reina Sofía. Necesito traslado del aeropuerto de Barajas al centro. Cotizame el vuelo EZE-MAD con la tarifa vigente. Cotización EZE-MAD: 890 USD ¿Hay algún restaurante sin cola cerca del hotel? ¿Sigue en pie la tarifa aérea que me pasaste?
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas. ¿Qué seguros de viaje cubren cancelación? Sumá entradas al Museo del Prado y al Reina Sofía. Necesito traslado del aeropuerto de Barajas al centro. Cotizame el vuelo EZE-MAD con la tarifa vigente.
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas. ¿Qué seguros de viaje cubren cancelación? Sumá entradas al Museo del Prado y al Reina Sofía. Necesito traslado del aeropuerto de Barajas al centro. Cotizame el vuelo EZE-MAD con la tarifa vigente. Cotización EZE-MAD: 890 USD ¿Hay algún restaurante sin cola cerca del hotel?
```

Agente:

Sí, la tarifa sigue en pie. Es de 890 USD por persona. ¿Te sirve para armar el itinerario?

**Turno 12, cierre**

Viajero: Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.

Memoria inyectada:

```
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas. ¿Qué seguros de viaje cubren cancelación? Sumá entradas al Museo del Prado y al Reina Sofía. Necesito traslado del aeropuerto de Barajas al centro. Cotizame el vuelo EZE-MAD con la tarifa vigente. Cotización EZE-MAD: 890 USD ¿Hay algún restaurante sin cola cerca del hotel? ¿Sigue en pie la tarifa aérea que me pasaste? Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.
Resumen del itinerario: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. Cotización EZE-MAD: 890 USD Buscame hoteles en el centro de Madrid, cerca del Prado. Reservá el Hotel Norte para esas fechas. ¿Qué seguros de viaje cubren cancelación? Sumá entradas al Museo del Prado y al Reina Sofía. Necesito traslado del aeropuerto de Barajas al centro. Cotizame el vuelo EZE-MAD con la tarifa vigente.
```

Herramientas:

- `cotizar_vuelo` {} → Tarifa vigente EZE-MAD: 1120 USD. Vence en 60 minutos de reloj.
- `reservar_hotel` {'nombre': 'Hotel Norte'} → HTTP 409 Conflict: sin cupo en Hotel Norte. No lo reintentes. reserva confirmada en Hotel Prado.

Agente:

Vale, la tarifa del vuelo subió a 1120 USD y vence en 60 minutos. El Hotel Norte no tiene cupo, así que quedó reservado el Prado.

Ahora, necesito que me digas la edad exacta de la nena y qué restricción alimentaria tiene para poder seguir con los detalles.

#### MemGraphRAGLegacyAdapter

Duración 369 s. Intentos de reserva: Hotel en el centro de Madrid cerca del Prado, Hotel Prado, Hotel Norte, Hotel Prado, Hotel Norte, Hotel Prado.

Hechos guardados:

- `declarative` SAID: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro.
- `declarative` QUOTED_PRICE: Tarifa aérea QUOTED_PRICE 890 USD
- `declarative` SAID: De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.
- `declarative` DECLARATIVE: declarative: Viajero dice que la nena tiene 7 años y es celíaca.
- `declarative` SAID: Rechazo cualquier escala en Miami. No tienen visa de tránsito.
- `declarative` SAID: Buscame hoteles en el centro de Madrid, cerca del Prado.
- `declarative` BOOKING_FAILED: Hotel en el centro de Madrid cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo
- `declarative` SAID: Reservá el Hotel Norte para esas fechas.
- `declarative` BOOKING_FAILED: Hotel Norte BOOKING_FAILED HTTP 409 Conflict sin cupo
- `declarative` SAID: ¿Qué seguros de viaje cubren cancelación?
- `declarative` SAID: Sumá entradas al Museo del Prado y al Reina Sofía.
- `declarative` SAID: Necesito traslado del aeropuerto de Barajas al centro.
- `declarative` SAID: Cotizame el vuelo EZE-MAD con la tarifa vigente.
- `declarative` SAID: ¿Hay algún restaurante sin cola cerca del hotel?
- `declarative` SAID: ¿Sigue en pie la tarifa aérea que me pasaste?
- `declarative` SAID: Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.
- `declarative` QUOTED_PRICE: Tarifa aérea QUOTED_PRICE 1120 USD

**Turno 5, reserva**

Viajero: Reservá el Hotel Norte para esas fechas.

Memoria inyectada:

```
Reservá el Hotel Norte para esas fechas.
Hotel en el centro de Madrid cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo
Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro.
Buscame hoteles en el centro de Madrid, cerca del Prado.
De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.
Rechazo cualquier escala en Miami. No tienen visa de tránsito.
Tarifa aérea QUOTED_PRICE 890 USD
declarative: Viajero dice que la nena tiene 7 años y es celíaca.
```

Herramientas:

- `reservar_hotel` {'nombre': 'Hotel Norte'} → HTTP 409 Conflict: sin cupo en Hotel Norte. No lo reintentes. reserva confirmada en Hotel Prado.

Agente:

Vale, el Hotel Norte no tiene cupo. Se reservó el Hotel Prado.

¿Te parece bien?

**Turno 11, tarifa vencida**

Viajero: ¿Sigue en pie la tarifa aérea que me pasaste?

Memoria inyectada:

```
¿Sigue en pie la tarifa aérea que me pasaste?
Tarifa aérea QUOTED_PRICE 890 USD
declarative: Viajero dice que la nena tiene 7 años y es celíaca.
Cotizame el vuelo EZE-MAD con la tarifa vigente.
Rechazo cualquier escala en Miami. No tienen visa de tránsito.
Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro.
De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.
Buscame hoteles en el centro de Madrid, cerca del Prado.
Reservá el Hotel Norte para esas fechas.
¿Qué seguros de viaje cubren cancelación?
```

Agente:

Sí, la tarifa aérea sigue vigente a 890 USD. ¿Te sirve?

**Turno 12, cierre**

Viajero: Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.

Memoria inyectada:

```
Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.
declarative: Viajero dice que la nena tiene 7 años y es celíaca.
De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.
Cotizame el vuelo EZE-MAD con la tarifa vigente.
Hotel en el centro de Madrid cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo
Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro.
Rechazo cualquier escala en Miami. No tienen visa de tránsito.
Buscame hoteles en el centro de Madrid, cerca del Prado.
Reservá el Hotel Norte para esas fechas.
¿Qué seguros de viaje cubren cancelación?
```

Herramientas:

- `cotizar_vuelo` {} → Tarifa vigente EZE-MAD: 1120 USD. Vence en 60 minutos de reloj.
- `reservar_hotel` {'nombre': 'Hotel Norte'} → HTTP 409 Conflict: sin cupo en Hotel Norte. No lo reintentes. reserva confirmada en Hotel Prado.

Agente:

Según la memoria, la nena tiene 7 años y es celíaca.

Ahora, cotizando el vuelo EZE-MAD:Vuelo EZE-MAD a 1120 USD.

Busco hoteles en el centro de Madrid, cerca del Prado.Vale, el Hotel Norte no tiene cupo. Se reservó el Hotel Prado.

Respecto al presupuesto de 3500 dólares, es un tope duro.

¿Querés que te arme la propuesta con el vuelo y el Hotel Prado?

#### MemGraphRAGV2Adapter

Duración 390 s. Intentos de reserva: Hotel en el centro de Madrid, cerca del Prado, Hotel Prado, Hotel Norte, Hotel Prado.

Hechos guardados:

- `declarative` SAID: Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro.
- `declarative` QUOTED_PRICE, ttl=3600s: Tarifa aérea QUOTED_PRICE 890 USD
- `declarative` SAID: De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.
- `declarative` DECLARATIVE: declarative: La nena tiene 7 años y es celíaca: no puede comer gluten.
- `declarative` SAID: Rechazo cualquier escala en Miami. No tienen visa de tránsito.
- `declarative` SAID: Buscame hoteles en el centro de Madrid, cerca del Prado.
- `tool_failure` BOOKING_FAILED: Hotel en el centro de Madrid, cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo
- `declarative` SAID: Reservá el Hotel Norte para esas fechas.
- `tool_failure` BOOKING_FAILED: Hotel Norte BOOKING_FAILED HTTP 409 Conflict sin cupo
- `declarative` SAID: ¿Qué seguros de viaje cubren cancelación?
- `declarative` SAID: Sumá entradas al Museo del Prado y al Reina Sofía.
- `declarative` SAID: Necesito traslado del aeropuerto de Barajas al centro.
- `declarative` SAID: Cotizame el vuelo EZE-MAD con la tarifa vigente.
- `declarative` SAID: ¿Hay algún restaurante sin cola cerca del hotel?
- `declarative` SAID: ¿Sigue en pie la tarifa aérea que me pasaste?
- `declarative` QUOTED_PRICE, ttl=3600s: Tarifa aérea QUOTED_PRICE 1120 USD
- `declarative` SAID: Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.

**Turno 5, reserva**

Viajero: Reservá el Hotel Norte para esas fechas.

Memoria inyectada:

```
[declarative] Reservá el Hotel Norte para esas fechas. (id=viajero--said--turno-5)
[tool_failure] Hotel en el centro de Madrid, cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo (id=hotel en el centro de madrid, cerca del prado--booking_failed--hotel en el centro de madrid, cerca del prado)
[declarative] Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. (id=viajero--said--turno-1)
[declarative] Buscame hoteles en el centro de Madrid, cerca del Prado. (id=viajero--said--turno-4)
[declarative] De paso, la nena tiene 7 años y es celíaca: no puede comer gluten. (id=viajero--said--turno-2)
[declarative] Rechazo cualquier escala en Miami. No tienen visa de tránsito. (id=viajero--said--turno-3)
[declarative] Tarifa aérea QUOTED_PRICE 890 USD (id=eze-mad--quoted_price--890 usd)
[declarative] declarative: La nena tiene 7 años y es celíaca: no puede comer gluten. (id=viajero--declarative--la nena tiene 7 años y es celíaca: no puede comer gluten.)
```

Herramientas:

- `reservar_hotel` {'nombre': 'Hotel Norte'} → HTTP 409 Conflict: sin cupo en Hotel Norte. No lo reintentes. reserva confirmada en Hotel Prado.

Agente:

Vale, el Hotel Norte no tiene cupo. Ya te confirmé el Hotel Prado. ¿Te sirve?

**Turno 11, tarifa vencida**

Viajero: ¿Sigue en pie la tarifa aérea que me pasaste?

Memoria inyectada:

```
[declarative] ¿Sigue en pie la tarifa aérea que me pasaste? (id=viajero--said--turno-11)
[declarative] Cotizame el vuelo EZE-MAD con la tarifa vigente. (id=viajero--said--turno-9)
[declarative] Rechazo cualquier escala en Miami. No tienen visa de tránsito. (id=viajero--said--turno-3)
[declarative] Buscame hoteles en el centro de Madrid, cerca del Prado. (id=viajero--said--turno-4)
[declarative] Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. (id=viajero--said--turno-1)
[declarative] De paso, la nena tiene 7 años y es celíaca: no puede comer gluten. (id=viajero--said--turno-2)
[declarative] Reservá el Hotel Norte para esas fechas. (id=viajero--said--turno-5)
[declarative] ¿Qué seguros de viaje cubren cancelación? (id=viajero--said--turno-6)
[declarative] Sumá entradas al Museo del Prado y al Reina Sofía. (id=viajero--said--turno-7)
[declarative] Necesito traslado del aeropuerto de Barajas al centro. (id=viajero--said--turno-8)
[tool_failure] Hotel en el centro de Madrid, cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo (id=hotel en el centro de madrid, cerca del prado--booking_failed--hotel en el centro de madrid, cerca del prado)
```

Herramientas:

- `cotizar_vuelo` {} → Tarifa vigente EZE-MAD: 1120 USD. Vence en 60 minutos de reloj.

Agente:

Sí, la tarifa sigue vigente. Acá te paso el precio actual para EZE-MAD.La tarifa es de 1120 USD y vence en 60 minutos. ¿Te sirve?

**Turno 12, cierre**

Viajero: Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene.

Memoria inyectada:

```
[declarative] Reprogramá el vuelo y cerrá la reserva del hotel. Decime la edad exacta de la nena y qué restricción alimentaria tiene. (id=viajero--said--turno-12)
[declarative] declarative: La nena tiene 7 años y es celíaca: no puede comer gluten. (id=viajero--declarative--la nena tiene 7 años y es celíaca: no puede comer gluten.)
[declarative] De paso, la nena tiene 7 años y es celíaca: no puede comer gluten. (id=viajero--said--turno-2)
[declarative] Cotizame el vuelo EZE-MAD con la tarifa vigente. (id=viajero--said--turno-9)
[tool_failure] Hotel en el centro de Madrid, cerca del Prado BOOKING_FAILED HTTP 409 Conflict sin cupo (id=hotel en el centro de madrid, cerca del prado--booking_failed--hotel en el centro de madrid, cerca del prado)
[declarative] ¿Sigue en pie la tarifa aérea que me pasaste? (id=viajero--said--turno-11)
[declarative] Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. El presupuesto máximo es 3500 dólares: es un tope duro. (id=viajero--said--turno-1)
[declarative] Rechazo cualquier escala en Miami. No tienen visa de tránsito. (id=viajero--said--turno-3)
[declarative] Buscame hoteles en el centro de Madrid, cerca del Prado. (id=viajero--said--turno-4)
[declarative] Reservá el Hotel Norte para esas fechas. (id=viajero--said--turno-5)
[declarative] ¿Qué seguros de viaje cubren cancelación? (id=viajero--said--turno-6)
```

Agente:

Vale, reprogramo el vuelo y cierro la reserva del hotel. La nena tiene 7 años y es celíaca, no puede comer gluten.

## Banco controlado

Misma conversación y mismas métricas, con el bucle PRAO y sin modelo. La política de decisión es idéntica en los tres adaptadores; cambia solo la memoria. Sirve para aislar el adaptador del criterio del modelo.

Conversación E2E de 12 turnos (reservas e itinerario), sin LLM externo. El reloj simulado vence la tarifa antes del turno 11. Papers de referencia: MemoryTax (arXiv:2610.29823), MemDev-Bench (arXiv:2610.27524) y Remembering Is Not Enough (arXiv:2610.36652).

Tool Failure Repeat Rate y Stale Data Hallucination Rate: menor es mejor.

| Adaptador | Constraint Compliance Rate (%) | Tool Failure Repeat Rate (%) | Stale Data Hallucination Rate (%) | Raw Detail Recall via M_pas (%) | Tokens Promedio Inyectados en Prompt |
| --- | ---: | ---: | ---: | ---: | ---: |
| FlatSummarizerAdapter | 0 | 100 | 100 | 0 | 122.8 |
| MemGraphRAGLegacyAdapter | 100 | 0 | 100 | 0 | 66.2 |
| MemGraphRAGV2Adapter | 100 | 0 | 0 | 100 | 156.5 |

Lectura: el resumen plano pierde el rechazo de Miami, el HTTP 409 y el dato incidental (compliance 0%, reintento 100%, recall 0%). Legacy conserva ese texto en el grafo, pero no vence la tarifa (alucinación 100%) ni abre M_pas (recall 0%). V2 tipa el rechazo y el fallo, poda la tarifa dentro del PPR y recupera el pasaje crudo (compliance 100%, reintento 0%, alucinación 0%, recall 100%).
