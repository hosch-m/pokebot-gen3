from enum import Enum
from typing import Generator

from modules.context import context
from modules.gui.multi_select_window import ask_for_choice, Selection
from modules.items import get_item_bag, get_item_by_name
from modules.memory import get_game_state, GameState
from modules.player import get_player, get_player_avatar
from modules.runtime import get_sprites_path
from modules.tasks import get_task
from ._asserts import assert_item_exists_in_bag
from ._interface import BotMode
from ._util import register_key_item


class TaskFishing(Enum):
    INIT = 0
    GET_ROD_OUT = 1
    WAIT_BEFORE_DOTS = 2
    INIT_DOTS = 3
    SHOW_DOTS = 4
    CHECK_FOR_BITE = 5
    GOT_BITE = 6
    WAIT_FOR_A = 7
    CHECK_MORE_DOTS = 8
    MON_ON_HOOK = 9
    START_ENCOUNTER = 10
    NOT_EVEN_NIBBLE = 11
    GOT_AWAY = 12
    NO_MON = 13
    PUT_ROD_AWAY = 14
    END_NO_MON = 15


class FishingMode(BotMode):
    @staticmethod
    def name() -> str:
        return "Fishing"

    @staticmethod
    def is_selectable() -> bool:
        player = get_player_avatar()
        targeted_tile = player.map_location_in_front
        return targeted_tile is not None and targeted_tile.is_surfable

    def run(self) -> Generator:
        rod_names = ("Old Rod", "Good Rod", "Super Rod")
        assert_item_exists_in_bag(rod_names, "You do not own any fishing rod, so you cannot fish.")

        if get_player().registered_item is None or get_player().registered_item.name not in rod_names:
            possible_rods = []
            for rod_name in rod_names:
                if get_item_bag().quantity_of(get_item_by_name(rod_name)) > 0:
                    possible_rods.append(rod_name)

            if len(possible_rods) == 1:
                rod_to_use = get_item_by_name(possible_rods[0])
            else:
                choices = []
                for rod in possible_rods:
                    choices.append(Selection(rod, get_sprites_path() / "items" / f"{rod} III.png"))
                rod_to_use = get_item_by_name(ask_for_choice(choices, window_title="Choose which rod to use"))

            yield from register_key_item(rod_to_use)

        while True:
            task_fishing = get_task("Task_Fishing")
            if task_fishing is not None:
                match task_fishing.data[0]:
                    case TaskFishing.WAIT_FOR_A.value | TaskFishing.END_NO_MON.value:
                        context.emulator.press_button("A")
                    case TaskFishing.NOT_EVEN_NIBBLE.value:
                        context.emulator.press_button("B")
                    case TaskFishing.START_ENCOUNTER.value:
                        context.emulator.press_button("A")
            elif get_game_state() == GameState.BATTLE:
                return
            else:
                context.emulator.press_button("Select")
            yield
