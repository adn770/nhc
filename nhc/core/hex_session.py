"""Hex overland and flower turn processing.

Extracted from Game to keep the god-object under control.
Manages hex movement, encounter staging, sub-hex flower
navigation, and hex world initialization.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nhc.core.actions import _count_slots_used, _item_slot_cost
from nhc.core.actions._hex_movement import MoveHexAction
from nhc.core.autosave import autosave as _autosave
from nhc.entities.components import (
    Description,
    Equipment,
    Health,
    Hunger,
    Inventory,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.generator import generate_continental_world
from nhc.hexcrawl.mode import Difficulty, WorldType
from nhc.hexcrawl.pack import load_pack
from nhc.i18n import t
from nhc.rules.chargen import generate_character, trait_text

if TYPE_CHECKING:
    from nhc.core.game import Game

logger = logging.getLogger(__name__)


class HexSession:
    """Drives hex overland and flower exploration on behalf of Game."""

    def __init__(self, game: Game) -> None:
        self.game = game

    # ── Convenience accessors ──────────────────────────────────────

    @property
    def world(self):
        return self.game.world

    @property
    def player_id(self):
        return self.game.player_id

    @property
    def renderer(self):
        return self.game.renderer

    # ── Hex movement ───────────────────────────────────────────────

    async def apply_hex_step(self, target: HexCoord) -> bool:
        """Execute a single overland step.

        Validates adjacency, runs :class:`MoveHexAction`, updates
        ``hex_player_position``, and writes an autosave. Returns
        True on success, False when the target is non-adjacent /
        out-of-bounds.

        Raises :class:`RuntimeError` when called outside hex mode so
        a miswired input handler fails loudly rather than silently
        corrupting the floor cache.
        """
        game = self.game
        if not game.world_type is WorldType.HEXCRAWL or game.hex_world is None:
            raise RuntimeError(
                "apply_hex_step only valid in hex mode"
            )
        origin = game.hex_player_position
        if origin is None:
            raise RuntimeError(
                "apply_hex_step requires hex_player_position to be set"
            )
        # First-visit detection: check before the move marks
        # the hex as visited.
        first_visit = not game.hex_world.is_visited(target)

        action = MoveHexAction(
            actor=self.player_id,
            origin=origin,
            target=target,
            hex_world=game.hex_world,
        )
        if not await action.validate(self.world, None):
            return False
        await action.execute(self.world, None)
        game.hex_world.record_entry_edge(origin, target)
        game.hex_player_position = target
        # Roll for a wilderness encounter on the target cell --
        # skipped on feature hexes (player is about to pick
        # enter-or-not) and when god mode disables encounters.
        self._maybe_stage_encounter(target)

        # First visit: auto-enter flower mode so the player
        # explores the sub-hex on their first arrival.
        if first_visit:
            cell = game.hex_world.get_cell(target)
            if cell and cell.flower:
                from nhc.hexcrawl._flowers import entry_sub_hex_for_edge
                edge = game.hex_world.last_entry_edge.get(target)
                entry_sub = entry_sub_hex_for_edge(edge)
                game.hex_world.enter_flower(target, entry_sub)

        _autosave(game, game.save_dir, blocking=True)
        return True

    def _maybe_stage_encounter(self, target: HexCoord) -> None:
        """Roll ``roll_encounter`` for the hex at ``target`` and stage
        the result on :attr:`pending_encounter`.

        Skipped when:
          * god mode has flipped :attr:`encounters_disabled`
          * an encounter is already pending (don't overwrite)
          * the target is a feature hex (cave / settlement / etc.)
            -- those invite "enter", not a random ambush
        """
        import random as _random

        from nhc.hexcrawl.encounter_pipeline import (
            rate_for_biome,
            roll_encounter,
        )
        from nhc.hexcrawl.model import HexFeatureType

        game = self.game
        if game.encounters_disabled:
            return
        if game.pending_encounter is not None:
            return
        if game.hex_world is None:
            return
        cell = game.hex_world.get_cell(target)
        if cell is None or cell.feature is not HexFeatureType.NONE:
            return
        rng = game._encounter_rng or _random.Random()
        # When the caller has left `encounter_rate` at its init
        # default, use the per-biome table so mountain passes
        # feel different from greenlands trails. Explicit overrides
        # (e.g. tests) still win.
        rate = game.encounter_rate
        if rate == game._default_encounter_rate:
            rate = rate_for_biome(cell.biome)
        enc = roll_encounter(
            cell.biome, rng, encounter_rate=rate,
        )
        if enc is not None:
            game.pending_encounter = enc

    # ── Player creation ────────────────────────────────────────────

    def _create_hex_player(self) -> None:
        """Create the ECS player entity for hex mode.

        Position is a sentinel with ``level_id == "overland"`` and
        ``(x, y) == (-1, -1)``; hex location is tracked in
        :attr:`hex_player_position` (moves via :meth:`apply_hex_step`).

        Character generation is identical to dungeon mode (same
        stats, HP, starting gear); hex-easy doubles the starting
        gold so the player can hire a henchman on the first town
        visit.
        """
        game = self.game
        char = generate_character(seed=game.seed)
        inv_slots = 10 + char.constitution
        gold = char.gold
        if game.difficulty is Difficulty.EASY:
            gold *= 2
        game.player_id = self.world.create_entity({
            "Position": Position(x=-1, y=-1, level_id="overland"),
            "Renderable": Renderable(
                glyph="@", color="dark_grey", render_order=10,
            ),
            "Stats": Stats(
                strength=char.strength,
                dexterity=char.dexterity,
                constitution=char.constitution,
                intelligence=char.intelligence,
                wisdom=char.wisdom,
                charisma=char.charisma,
            ),
            "Health": Health(current=char.hp, maximum=char.hp),
            "Inventory": Inventory(max_slots=inv_slots),
            "Player": Player(gold=gold),
            "Description": Description(
                name=char.name,
                short=trait_text("background", char.background),
            ),
            "Equipment": Equipment(),
            "Hunger": Hunger(),
        })
        game._character = char
        game._give_starting_gear(char)

    # ── Hex world initialization ───────────────────────────────────

    def _init_hex_world(self) -> None:
        """Build the overland HexWorld for the configured hex mode.

        Difficulty rules (see ``design/overland_hexcrawl.md`` §2):

        * ``HEX_EASY`` -- player starts on the hub hex; the hub is
          revealed.
        * ``HEX_SURVIVAL`` -- player starts on a random non-feature
          hex; the hub is *not* revealed.

        Neighbour reveal on first step is the responsibility of
        ``MoveHexAction`` (M-1.5 / M-1.6); the initial reveal here
        is exactly one hex.
        """
        game = self.game
        # Path-relative load of the bundled pack. A future
        # milestone will let the caller pick a pack via the CLI.
        pack_path = (
            Path(__file__).resolve().parents[2]
            / "content" / "testland" / "pack.yaml"
        )
        pack = load_pack(pack_path)
        # Dispatcher: pick the generator named in the pack.
        # Unknown generators are rejected at pack-load time
        # (KNOWN_GENERATORS) so we only need to handle the
        # currently-shipped set here.
        game.hex_world = generate_continental_world(
            seed=game.seed, pack=pack,
        )
        self._create_hex_player()

        from nhc.hexcrawl._flowers import pick_flower_start
        macro, sub = pick_flower_start(
            game.hex_world, game.difficulty,
            seed=(game.seed or 0) ^ 0xABCD1234,
        )
        game.hex_player_position = macro
        game.hex_world.visit(macro)

        if game.difficulty is not Difficulty.SURVIVAL:
            hub = game.hex_world.last_hub
            assert hub is not None, "generator must set last_hub"
            game.hex_world.reveal(hub)

        if game.difficulty is Difficulty.SURVIVAL:
            game.hex_world.revealed.clear()
            game.hex_world.reveal(macro)

        # Enter flower view directly
        game.hex_world.enter_flower(macro, sub)
        self.renderer.add_message(
            "You begin your journey. Move with y/u/n/b/j/k. "
            "Press 'x' to enter a feature. Press 'L' to leave."
        )

    # ── Turn processing ────────────────────────────────────────────

    async def _process_hex_turn(self) -> str:
        """Handle one overland input event.

        Returns ``"disconnect"`` on WebSocket teardown, otherwise a
        descriptive tag for the event ("moved", "entered", "rest",
        "ignored"). The game loop consults the return value only
        for the disconnect branch.
        """
        game = self.game
        intent, data = await self.renderer.get_input()
        if intent == "disconnect":
            return "disconnect"
        if intent == "hex_step" and data:
            origin = game.hex_player_position
            if origin is None:
                return "ignored"
            dq, dr = data
            target = HexCoord(origin.q + int(dq), origin.r + int(dr))
            ok = await self.apply_hex_step(target)
            if not ok:
                self.renderer.add_message(t("hex.msg.cant_go_that_way"))
            else:
                # Overland travel ticks hunger the same way a
                # dungeon turn does (game_ticks.tick_hunger). The
                # inner call also surfaces any state-transition
                # messages ("You're getting hungry.", starvation
                # damage, etc.).
                game._tick_hunger()
                if game.pending_encounter is not None:
                    await self._prompt_encounter()
            return "moved" if ok else "ignored"
        if intent == "hex_explore":
            # Enter the current hex's flower for sub-hex exploration.
            coord = game.hex_player_position
            cell = (
                game.hex_world.get_cell(coord)
                if game.hex_world and coord else None
            )
            if cell and cell.flower:
                from nhc.hexcrawl._flowers import entry_sub_hex_for_edge
                # Prefer the sub-hex the player was on when they
                # last exited this hex's flower. Falls back to the
                # default entry-edge sub-hex on first entry (or
                # when the stash was cleared by some other path).
                # Without this preference the round-trip flower ->
                # hex -> flower snaps the player back to the
                # center sub-hex instead of where they left.
                entry_sub = game.hex_world.last_sub_hex_by_macro.get(
                    coord,
                )
                if entry_sub is None:
                    edge = game.hex_world.last_entry_edge.get(coord)
                    entry_sub = entry_sub_hex_for_edge(edge)
                game.hex_world.enter_flower(coord, entry_sub)
                self.renderer.add_message("You begin exploring.")
                return "moved"
            self.renderer.add_message(
                "There is nothing to explore here.",
            )
            return "ignored"
        if intent == "hex_rest":
            # +1 full day, a full heal, and a meal -- rest ticks
            # the clock and pays out both HP and hunger. A day
            # at camp assumes rations were available to eat.
            game.hex_world.advance_clock(4)
            health = self.world.get_component(
                self.player_id, "Health",
            )
            if health is not None:
                health.current = health.maximum
            hunger = self.world.get_component(
                self.player_id, "Hunger",
            )
            if hunger is not None:
                hunger.current = hunger.maximum
                hunger.prev_state = "satiated"
            self.renderer.add_message(
                f"You rest. Day {game.hex_world.day} dawns.",
            )
            return "rest"
        # Unknown intents silently ignored so a stray keyboard event
        # doesn't end the turn with no visible effect.
        return "ignored"

    async def _process_flower_turn(self) -> str:
        """Handle one sub-hex exploration input event.

        Returns ``"disconnect"`` on WebSocket teardown, otherwise
        a descriptive tag for the event.
        """
        from nhc.core.actions._sub_hex_movement import MoveSubHexAction
        from nhc.hexcrawl._flowers import get_exit_edge
        from nhc.hexcrawl.coords import direction_index
        from nhc.hexcrawl.encounter_pipeline import (
            rate_for_biome,
            roll_encounter,
        )
        import random as _random

        game = self.game
        intent, data = await self.renderer.get_input()
        if intent == "disconnect":
            return "disconnect"

        if intent == "flower_step" and data:
            sub_pos = game.hex_world.exploring_sub_hex
            if sub_pos is None:
                return "ignored"
            dq, dr = data
            target_sub = HexCoord(sub_pos.q + int(dq), sub_pos.r + int(dr))

            # Check if stepping outside the flower (exit)
            exit_edge = get_exit_edge(sub_pos, target_sub)
            if exit_edge is not None:
                from nhc.hexcrawl.coords import NEIGHBOR_OFFSETS
                macro = game.hex_world.exploring_hex
                edq, edr = NEIGHBOR_OFFSETS[exit_edge]
                new_macro = HexCoord(macro.q + edq, macro.r + edr)
                game.hex_world.exit_flower()
                if game.hex_world.is_in_shape(new_macro):
                    game.hex_world.visit(new_macro)
                    game.hex_player_position = new_macro
                    self.renderer.add_message(
                        t("hex.msg.leave_area"),
                    )
                else:
                    self.renderer.add_message(
                        t("hex.msg.cant_go_that_way"),
                    )
                return "moved"

            action = MoveSubHexAction(
                actor=self.player_id,
                origin=sub_pos,
                target=target_sub,
                hex_world=game.hex_world,
            )
            if not action.validate_sync():
                self.renderer.add_message(t("hex.msg.cant_go_that_way"))
                return "ignored"
            action.execute_sync()
            game._tick_hunger()
            # Sub-hex encounter check at lower rate
            self._maybe_stage_sub_hex_encounter(target_sub)
            if game.pending_encounter is not None:
                await self._prompt_encounter()
            return "moved"

        if intent == "flower_exit":
            game.hex_world.exit_flower()
            self.renderer.add_message(t("hex.msg.return_overland"))
            return "moved"

        if intent == "flower_search":
            from nhc.core.actions._sub_hex_actions import (
                SearchSubHexAction,
            )
            action = SearchSubHexAction(
                actor=self.player_id, hex_world=game.hex_world,
            )
            if not action.validate_sync():
                self.renderer.add_message(
                    "Nothing more to find here.",
                )
                return "ignored"
            events = action.execute_sync()
            for ev in events:
                if hasattr(ev, "text"):
                    self.renderer.add_message(ev.text)
            return "moved"

        if intent == "flower_forage":
            from nhc.core.actions._sub_hex_actions import (
                ForageSubHexAction,
            )
            action = ForageSubHexAction(
                actor=self.player_id, hex_world=game.hex_world,
            )
            if not action.validate_sync():
                return "ignored"
            events = action.execute_sync()
            for ev in events:
                if hasattr(ev, "text"):
                    self.renderer.add_message(ev.text)
            return "moved"

        if intent == "flower_rest":
            from nhc.core.actions._sub_hex_actions import (
                RestSubHexAction,
            )
            action = RestSubHexAction(
                actor=self.player_id,
                hex_world=game.hex_world,
                ecs_world=self.world,
            )
            events = action.execute_sync()
            for ev in events:
                if hasattr(ev, "text"):
                    self.renderer.add_message(ev.text)
            self._maybe_stage_sub_hex_encounter(
                game.hex_world.exploring_sub_hex,
            )
            if game.pending_encounter is not None:
                await self._prompt_encounter()
            return "rest"

        if intent == "hex_enter":
            # Sub-hex entry: dispatch on the content of the sub-hex
            # the player is standing on, not the flower's feature
            # cell. Each sub-hex with a feature is independently
            # enterable; the old "feature_cell gate" is gone.
            from nhc.core.sub_hex_entry import resolve_sub_hex_entry
            from nhc.sites._types import SiteTier

            macro = game.hex_world.exploring_hex
            sub = game.hex_world.exploring_sub_hex
            cell = game.hex_world.get_cell(macro) if macro else None
            if (
                cell is None or cell.flower is None
                or sub is None
            ):
                self.renderer.add_message(
                    t("hex.msg.nothing_to_enter"),
                )
                return "ignored"
            sub_cell = cell.flower.cells.get(sub)
            if sub_cell is None:
                self.renderer.add_message(
                    t("hex.msg.nothing_to_enter"),
                )
                return "ignored"

            resolved = resolve_sub_hex_entry(sub_cell)
            if resolved is None:
                self.renderer.add_message(
                    t("hex.msg.nothing_to_enter"),
                )
                return "ignored"

            if resolved[0] == "non-enterable":
                reason = resolved[1]
                self.renderer.add_message(
                    t(
                        "hex.msg.blocks_way",
                        feature=t(f"hex.feature.{reason}"),
                    ),
                )
                return "ignored"

            if resolved[0] == "bespoke":
                # Existing macro pipeline reads ``hex_player_position``
                # and the macro cell's DungeonRef. The sub-hex's
                # folded DungeonRef means even non-feature_cell
                # sub-hexes could in principle dispatch here, but
                # today only the feature_cell carries the ref.
                ok = await game.enter_hex_feature()
                if ok:
                    feature_key = cell.feature.value
                    self.renderer.add_message(
                        t(
                            "hex.msg.enter_feature",
                            feature=t(f"hex.feature.{feature_key}"),
                        ),
                    )
                else:
                    self.renderer.add_message(
                        t("hex.msg.nothing_to_enter"),
                    )
                return "entered" if ok else "ignored"

            if resolved[0] == "family":
                _, family, feature = resolved
                # Family tier: TINY for wayside / natural
                # curiosity (single-feature minor sites), SMALL
                # for everyone else (sacred / den / settlement /
                # graveyard / etc.). MEDIUM and up are reserved
                # for macro-scale sites tier-ised in M6b.
                if family in ("wayside", "natural_curiosity"):
                    tier = SiteTier.TINY
                else:
                    tier = SiteTier.SMALL
                ok = await game.enter_sub_hex_family_site(
                    macro, sub, family, feature, tier,
                    sub_cell.biome,
                )
                if ok:
                    self.renderer.add_message(
                        t(
                            "hex.msg.enter_feature",
                            feature=t(f"hex.minor.{feature.value}"),
                        ),
                    )
                else:
                    self.renderer.add_message(
                        t("hex.msg.nothing_to_enter"),
                    )
                return "entered" if ok else "ignored"

            self.renderer.add_message(
                t("hex.msg.nothing_to_enter"),
            )
            return "ignored"

        return "ignored"

    def _maybe_stage_sub_hex_encounter(
        self, target_sub: HexCoord,
    ) -> None:
        """Roll encounter at sub-hex level (~15% of macro rate)."""
        import random as _random
        from nhc.hexcrawl.encounter_pipeline import (
            rate_for_biome,
            roll_encounter,
        )

        game = self.game
        if game.encounters_disabled:
            return
        if game.pending_encounter is not None:
            return
        macro = game.hex_world.exploring_hex
        if macro is None:
            return
        cell = game.hex_world.get_cell(macro)
        if cell is None or cell.flower is None:
            return
        sub_cell = cell.flower.cells.get(target_sub)
        if sub_cell is None:
            return
        rng = game._encounter_rng or _random.Random()
        base_rate = rate_for_biome(sub_cell.biome) * 0.15
        rate = base_rate * sub_cell.encounter_modifier
        enc = roll_encounter(
            sub_cell.biome, rng, encounter_rate=rate,
        )
        if enc is not None:
            game.pending_encounter = enc

    async def _prompt_encounter(self) -> None:
        """Surface a pending encounter to the player.

        Pops the Fight / Flee / Talk menu via
        ``renderer.show_selection_menu`` and dispatches the pick
        through :meth:`resolve_encounter`. A missing renderer hook
        or a cancelled menu auto-resolves to Flee so the world
        doesn't stall with an unconsumed pending encounter -- the
        player takes the chicken tax and keeps moving.
        """
        from nhc.hexcrawl.encounter_pipeline import EncounterChoice
        game = self.game
        enc = game.pending_encounter
        if enc is None:
            return
        prompt = getattr(
            self.renderer, "show_selection_menu", None,
        )
        if prompt is None:
            await game.resolve_encounter(EncounterChoice.FLEE)
            return
        options: list[tuple[str, str]] = [
            (EncounterChoice.FIGHT.value, t("encounter.fight")),
            (EncounterChoice.FLEE.value, t("encounter.flee")),
            (EncounterChoice.TALK.value, t("encounter.talk")),
        ]
        # Describe the foes in natural language so the prompt
        # reads "You run into 2 goblins and a kobold" with
        # localized plural + gender + articles.
        from nhc.hexcrawl.encounter_text import (
            format_encounter_creatures,
        )
        creatures_text = format_encounter_creatures(enc.creatures)
        biome_label = t(f"hex.biome.{enc.biome.value}")
        title = t(
            "encounter.prompt",
            creatures=creatures_text,
            biome=biome_label,
        )
        choice = prompt(title, options)
        if choice is None:
            choice = EncounterChoice.FLEE.value
        try:
            resolved = EncounterChoice(choice)
        except ValueError:
            resolved = EncounterChoice.FLEE
        await game.resolve_encounter(resolved)
