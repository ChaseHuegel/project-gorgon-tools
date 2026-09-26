from gorgon_tracker.correlator import (
    ActivityEvent,
    BuryEvent,
    CorpseSearch,
    Correlator,
    InteractionStart,
    LootEvent,
    SourceEvent,
    TargetSighting,
    ZoneChange,
)


def make(sec: float) -> int:
    return round(sec * 1000)


def src(sec: float, monster: str, skin=False, butcher=False, extract=False) -> SourceEvent:
    return SourceEvent(time_ms=make(sec), monster=monster, can_skin=skin, can_butcher=butcher, can_extract=extract)


def loot(sec: float, item: str, amount=1) -> LootEvent:
    return LootEvent(time_ms=make(sec), item=item, amount=amount)


def _run(correlator: Correlator, events) -> list:
    for kind, event in events:
        if kind == "zone":
            correlator.ingest_zone_change(event)
        elif kind == "target":
            correlator.ingest_target(event)
        elif kind == "loot":
            correlator.ingest_loot(event)
        elif kind == "bury":
            correlator.ingest_bury(event)
        elif kind == "source":
            correlator.ingest_source(event)
        elif kind == "corpse":
            correlator.ingest_corpse_search(event)
        elif kind == "interaction":
            correlator.ingest_interaction(event)
        elif kind == "activity":
            correlator.ingest_activity(event)
    return correlator.finalize()


def test_links_drop_to_most_recent_source() -> None:
    c = Correlator()
    drops = _run(c, [("source", src(1.0, "Rat")), ("loot", loot(3.0, "Bone")), ("source", src(4.0, "Rat"))])
    assert len(drops) == 1
    assert drops[0].source == "Rat"
    assert drops[0].status == "Linked"
    assert drops[0].lag_ms == 1000
    assert drops[0].activity == "Looting"
    assert drops[0].zone == "Unknown"


def test_orphan_uses_target_sighting() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("target", TargetSighting(time_ms=make(9.5), name="Dire Wolf")),
            ("loot", loot(10.0, "Pelt")),
            ("source", src(12.0, "Dire Wolf")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].source == "Dire Wolf"
    assert drops[0].status == "Linked"  # linked via target, not monster
    assert drops[0].lag_ms == 500


def test_ground_orphan_when_no_source_or_target() -> None:
    c = Correlator()
    drops = _run(c, [("loot", loot(10.0, "Twig")), ("bury", BuryEvent(time_ms=make(11.0)))])
    assert len(drops) == 1
    assert drops[0].source == "Ground/Unknown"
    assert drops[0].status == "Orphaned"
    assert drops[0].lag_ms == 0


def test_retroactive_skinning() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Giant Bat", skin=True)),
            ("loot", loot(0.5, "Bat Wing")),
            ("source", src(1.0, "Giant Bat", skin=False)),
        ],
    )
    assert len(drops) == 1
    assert drops[0].activity == "Skinning"
    assert drops[0].lag_ms == 500


def test_butchering_and_extracting() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Boar", butcher=True)),
            ("loot", loot(0.2, "Bacon")),
            ("source", src(1.0, "Boar", extract=True)),
            ("loot", loot(1.2, "Skull")),
            ("source", src(2.0, "Boar")),
        ],
    )
    assert [d.activity for d in drops] == ["Butchering", "Extracting"]


def test_session_timeout_starts_new_encounter_and_resets_activity() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat", skin=True)),
            ("source", src(5.0, "Rat", skin=False)),  # 5s gap, 3s timeout -> new encounter
            ("loot", loot(5.5, "Bone")),
            ("source", src(6.0, "Rat")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].activity == "Looting"  # no retroactive skin because new encounter
    assert drops[0].status == "Linked"


def test_skin_flag_updates_across_sources() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat", skin=True)),
            ("loot", loot(0.5, "Bone")),
            ("source", src(1.0, "Rat", skin=False)),
        ],
    )
    assert drops[0].activity == "Skinning"
    assert len(drops[0].encounter_uuid) == 36  # uuid4 shape


def test_bury_links_pending_drops_to_last_monster() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat")),
            ("loot", loot(1.0, "Bone")),
            ("loot", loot(1.5, "Pelt", 2)),
            ("bury", BuryEvent(time_ms=make(2.0))),
        ],
    )
    assert len(drops) == 2
    assert all(d.source == "Rat" and d.status == "Linked" for d in drops)
    assert [d.lag_ms for d in drops] == [1000, 500]


def test_zone_tracks_changes() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("zone", ZoneChange(time_ms=make(0.0), zone="Old Graveyard")),
            ("source", src(1.0, "Rat")),
            ("loot", loot(2.0, "Bone")),
            ("source", src(3.0, "Rat")),
            ("zone", ZoneChange(time_ms=make(4.0), zone="Fairy Glen")),
            ("source", src(5.0, "Wolf")),
            ("loot", loot(6.0, "Pelt")),
            ("source", src(7.0, "Wolf")),
        ],
    )
    assert [d.zone for d in drops] == ["Old Graveyard", "Fairy Glen"]


def test_finalize_flushes_pending() -> None:
    c = Correlator()
    drops = _run(c, [("source", src(0.0, "Rat")), ("loot", loot(1.0, "Bone"))])
    assert len(drops) == 1
    assert drops[0].source == "Rat"
    assert drops[0].lag_ms == 0


def test_take_drops_clears_and_streams_produced_drops() -> None:
    c = Correlator(buffer_seconds=10.0)
    c.ingest_source(src(0.0, "Rat"))
    c.ingest_loot(loot(1.0, "Bone"))
    c.ingest_source(src(2.0, "Rat"))
    streamed = c.take_drops()
    assert len(streamed) == 1
    assert streamed[0].source == "Rat"
    assert c.take_drops() == []  # already drained


def test_flush_expired_orphans_stale_pending_without_ref_time() -> None:
    c = Correlator(buffer_seconds=5.0)
    c.ingest_loot(loot(0.0, "Twig"))
    c.ingest_loot(loot(1.0, "Bone"))
    stale = c.flush_expired(make(20.0))
    assert len(stale) == 2
    assert all(d.status == "Orphaned" for d in stale)
    assert all(d.source == "Ground/Unknown" for d in stale)
    assert c.pending == []  # cleared
    assert c.flush_expired(make(30.0)) == []


def test_flush_expired_does_not_resurface_in_take_drops() -> None:
    """Regression: flushed drops must be emitted once, not drained again later."""
    c = Correlator(buffer_seconds=5.0)
    c.ingest_loot(loot(0.0, "Twig"))
    c.ingest_loot(loot(1.0, "Bone"))
    emitted = c.flush_expired(make(20.0))
    assert len(emitted) == 2
    assert c.take_drops() == []  # must not re-deliver already-emitted drops
    assert c.finalize() == []    # nor via finalize at stream end


def test_flush_expired_keeps_recent_pending() -> None:
    c = Correlator(buffer_seconds=10.0)
    c.ingest_loot(loot(5.0, "Bone"))
    c.ingest_loot(loot(19.5, "Pelt"))
    stale = c.flush_expired(make(20.0))
    assert [d.item for d in stale] == ["Bone"]
    assert c.pending == [loot(19.5, "Pelt")]


# --- evidence + harvestable classification -----------------------------------


def test_monster_link_records_evidence() -> None:
    c = Correlator()
    drops = _run(c, [("source", src(1.0, "Rat")), ("loot", loot(3.0, "Bone")), ("source", src(4.0, "Rat"))])
    drop = drops[0]
    assert drop.linked_via == "monster"
    assert drop.monster_name == "Rat"
    assert drop.monster_lag_ms == 1000
    assert drop.corroborated_by_search is False


def test_target_link_is_harvesting_without_corpse_search() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("target", TargetSighting(time_ms=make(3.8), name="Flower")),
            ("loot", loot(4.0, "Golden Flower")),
            ("bury", BuryEvent(time_ms=make(5.0))),
        ],
    )
    assert len(drops) == 1
    drop = drops[0]
    assert drop.linked_via == "target"
    assert drop.source == "Flower"
    assert drop.activity == "Harvesting"
    assert drop.corroborated_by_search is False
    assert drop.target_lag_ms == 200


def test_target_link_corroborated_by_search_stays_looting() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(2.0, "Dire Wolf")),
            ("target", TargetSighting(time_ms=make(3.8), name="Dire Wolf")),
            ("loot", loot(4.0, "Wolf Pelt")),
            ("bury", BuryEvent(time_ms=make(5.0))),
        ],
    )
    assert len(drops) == 1
    drop = drops[0]
    assert drop.linked_via == "target"
    assert drop.activity == "Looting"  # same-name corpse search within 2s
    assert drop.corroborated_by_search is True


def test_stale_target_sighting_is_ineligible() -> None:
    c = Correlator(target_fallback_seconds=3.0)
    drops = _run(
        c,
        [
            ("target", TargetSighting(time_ms=make(1.0), name="Dire Wolf")),
            ("loot", loot(6.0, "Bone")),
            ("bury", BuryEvent(time_ms=make(7.0))),
        ],
    )
    assert len(drops) == 1
    drop = drops[0]
    assert drop.linked_via == "orphan"
    assert drop.status == "Orphaned"
    assert drop.source == "Ground/Unknown"


def test_fresh_target_beats_stale_orphan_only_if_within_window() -> None:
    c = Correlator(target_fallback_seconds=3.0)
    drops = _run(
        c,
        [
            ("target", TargetSighting(time_ms=make(9.5), name="Flower")),
            ("loot", loot(10.0, "Petal")),  # sighting 0.5s before: eligible
            ("loot", loot(13.5, "Twig")),  # sighting 4s before: ineligible
            ("bury", BuryEvent(time_ms=make(14.5))),
        ],
    )
    by_item = {d.item: d for d in drops}
    assert by_item["Petal"].linked_via == "target"
    assert by_item["Petal"].source == "Flower"
    assert by_item["Twig"].linked_via == "orphan"
    assert by_item["Twig"].status == "Orphaned"


# --- Unity Player.log reconciliation + corpse attribution -------------------


def _unity(sec: float, item: str, amount=1, instance=None, missed=False) -> LootEvent:
    return LootEvent(
        time_ms=make(sec) - make(sec) % 1000,
        item=item,
        amount=amount,
        instance_id=instance,
        source_class="unity",
        missed=missed,
    )


def test_chat_and_unity_same_second_reconcile_to_one_drop() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(1.0, "Rat")),
            ("loot", loot(2.0, "Good Armor Patch Kit")),
            ("loot", _unity(2.0, "ArmorPatchKit3", instance=-1719914656)),
            ("source", src(3.0, "Rat")),
        ],
    )
    assert len(drops) == 1
    drop = drops[0]
    assert drop.amount == 1
    assert drop.status == "Linked"


def test_chat_quantity_wins_when_pairing_stacks() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(1.0, "Hog")),
            ("loot", loot(2.0, "Basic Reservoir Arrow", 24)),
            ("loot", _unity(2.0, "ReservoirArrow2", instance=-1719915134)),
            ("source", src(3.0, "Hog")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].amount == 24


def test_unity_only_pickup_infers_display_name() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(1.0, "Wolf")),
            ("loot", _unity(2.0, "StrikingBell", instance=-1726463684)),
            ("source", src(3.0, "Wolf")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].item == "Striking Bell"
    assert drops[0].instance_id == -1726463684


def test_corpse_search_attributes_loot_and_killer() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("interaction", InteractionStart(time_ms=make(1.0), entity_id=1001)),
            ("loot", loot(2.0, "Gottak's Calling Card")),
            ("loot", _unity(2.0, "GoblinCallingCard15", instance=-1719916789)),
            (
                "corpse",
                CorpseSearch(
                    time_ms=make(3.0),
                    monster="Goblin Horsebeater",
                    entity_id=1001,
                    killer="Mennelaia",
                    participants={"Mennelaia": {"health": 319, "armor": 273, "aggro": 18.52}},
                    extractions={"extracted": "Impressive Goblin Skull"},
                ),
            ),
            ("bury", BuryEvent(time_ms=make(4.0))),
        ],
    )
    assert len(drops) == 1
    drop = drops[0]
    assert drop.source == "Goblin Horsebeater"
    assert drop.status == "Linked"
    assert drop.killer_json is not None and "Mennelaia" in drop.killer_json


def test_missed_loot_is_flagged_missed() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(1.0, "Rat")),
            ("loot", _unity(2.0, "Unknown", instance=-1, missed=True)),
            ("source", src(3.0, "Rat")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].status == "Missed"
    assert drops[0].missed is True


# --- corpse-description activity transitions (Unity Player.log) ----------------


def _corpse(sec: float, monster: str, entity_id: int, extractions=None) -> CorpseSearch:
    return CorpseSearch(
        time_ms=make(sec),
        monster=monster,
        entity_id=entity_id,
        extractions=extractions or {},
    )


def test_corpse_description_transition_marks_skinning() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("interaction", InteractionStart(time_ms=make(1.0), entity_id=501)),
            ("corpse", _corpse(2.0, "Giant Bat", 501)),
            ("loot", loot(3.0, "Bat Wing")),
            ("corpse", _corpse(4.0, "Giant Bat", 501, {"skinned": "Bat Wing"})),
        ],
    )
    assert len(drops) == 1
    assert drops[0].source == "Giant Bat"
    assert drops[0].activity == "Skinning"


def test_corpse_description_butcher_and_extract_transitions() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("interaction", InteractionStart(time_ms=make(1.0), entity_id=601)),
            ("corpse", _corpse(2.0, "Boar", 601)),
            ("loot", loot(3.0, "Pork")),
            ("corpse", _corpse(4.0, "Boar", 601, {"butchered": "Pork"})),
            ("loot", loot(5.0, "Skull")),
            ("corpse", _corpse(6.0, "Boar", 601, {"butchered": "Pork", "extracted": "Skull"})),
        ],
    )
    assert [d.activity for d in drops] == ["Butchering", "Extracting"]


def test_corpse_first_seen_already_skinned_stays_looting() -> None:
    """A corpse that already shows skinned when first searched is not a fresh action."""
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("interaction", InteractionStart(time_ms=make(1.0), entity_id=501)),
            ("loot", loot(3.0, "Bat Wing")),
            ("corpse", _corpse(4.0, "Giant Bat", 501, {"skinned": "Bat Wing"})),
        ],
    )
    assert drops[0].activity == "Looting"


def test_corpse_repeated_skinned_state_stays_looting() -> None:
    """Sequential searches already showing skinned never relabel as skinning."""
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("interaction", InteractionStart(time_ms=make(1.0), entity_id=501)),
            ("corpse", _corpse(2.0, "Giant Bat", 501, {"skinned": "Bat Wing"})),
            ("loot", loot(3.0, "Bat Wing")),
            ("corpse", _corpse(4.0, "Giant Bat", 501, {"skinned": "Bat Wing"})),
        ],
    )
    assert drops[0].activity == "Looting"


# --- chat status activity markers ---------------------------------------------


def test_chat_activity_marker_labels_drop_linked_to_monster() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("source", src(1.0, "Boar")),
            ("loot", loot(3.0, "Pork")),
            ("activity", ActivityEvent(time_ms=make(4.0), activity="Butchering")),
            ("source", src(5.0, "Boar")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].source == "Boar"
    assert drops[0].status == "Linked"
    assert drops[0].activity == "Butchering"


def test_chat_activity_marker_labels_orphan_drop() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("loot", loot(3.0, "Pork")),
            ("activity", ActivityEvent(time_ms=make(4.0), activity="Butchering")),
            ("bury", BuryEvent(time_ms=make(5.0))),
        ],
    )
    assert drops[0].activity == "Butchering"


def test_chat_activity_marker_outside_window_stays_looting() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("source", src(1.0, "Boar")),
            ("loot", loot(10.0, "Pork")),
            ("activity", ActivityEvent(time_ms=make(13.0), activity="Butchering")),
        ],
    )
    assert drops[0].activity == "Looting"


def test_bury_clears_activity_hint() -> None:
    c = Correlator(activity_window_seconds=2.0)
    drops = _run(
        c,
        [
            ("activity", ActivityEvent(time_ms=make(1.0), activity="Skinning")),
            ("bury", BuryEvent(time_ms=make(2.0))),
            ("loot", loot(3.0, "Bat Wing")),
        ],
    )
    assert drops[0].activity == "Looting"