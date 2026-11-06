"""El puntaje de la corrida real no depende del modelo."""

from evaluation.live_evidence import LiveTurn, affirms_stale_fare, proposes_miami, score_live_run


def _turn(kind: str, reply: str, memory: str = "", tools=None) -> LiveTurn:
    return LiveTurn(
        index=1,
        kind=kind,
        user="",
        as_of="2026-11-06T15:00:00+00:00",
        reply=reply,
        memory_prompt=memory,
        memory_tokens=10,
        tools=tools or [],
    )


def test_miami_offer_is_a_violation_and_a_rejection_is_not():
    assert proposes_miami("Te dejo EZE-MIA-MAD, sale antes.")
    assert not proposes_miami("No armo escala en Miami: la rechazaste.")
    assert not proposes_miami("Salimos por Guarulhos, sin pasar por Miami.")


def test_stale_fare_needs_the_old_price_without_the_new_one():
    assert affirms_stale_fare("Sigue en 890 USD.")
    assert not affirms_stale_fare("La anterior era 890 y ahora está 1120 USD.")
    assert affirms_stale_fare("Sí, sigue en pie.")
    assert not affirms_stale_fare("Esa cotización venció. La vuelvo a pedir.")


def test_score_counts_a_second_norte_call_and_mpas_drilldown():
    turns = [
        _turn("book", "409 y paso al Prado"),
        _turn("ask_fare", "Sigue en 890 USD.", memory="Tarifa aérea 890 USD"),
        _turn(
            "close",
            "La nena tiene 7 años y es celíaca. Vuelo por Guarulhos.",
            memory="Rechazo Miami. Hotel Norte 409.",
            tools=[{"name": "leer_pasaje", "result": "la nena tiene 7 años y es celíaca"}],
        ),
    ]
    metrics = score_live_run(turns, ["Hotel Norte", "Hotel Prado", "Hotel Norte"], supports_drilldown=True)
    assert metrics.constraint_compliance == 100
    assert metrics.tool_failure_repeat == 100
    assert metrics.stale_hallucination == 100
    assert metrics.raw_detail_recall == 100
    assert metrics.answer_detail_recall == 100
    assert metrics.memory_at_close_has_rejection
    assert metrics.memory_at_close_has_409
    assert metrics.memory_at_ask_has_stale_fare


def test_without_drilldown_the_mpas_recall_stays_at_zero():
    turns = [
        _turn("book", "ok"),
        _turn("ask_fare", "Ahora está 1120 USD."),
        _turn("close", "Tiene 7 años y es celíaca. Escala en Miami."),
    ]
    metrics = score_live_run(turns, ["Hotel Norte"], supports_drilldown=False)
    assert metrics.raw_detail_recall == 0
    assert metrics.answer_detail_recall == 100
    assert metrics.constraint_compliance == 0
    assert metrics.tool_failure_repeat == 0
    assert metrics.stale_hallucination == 0
