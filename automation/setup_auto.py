"""
Automation Helper: Setup (TUI)
Interactive Textual wizard to configure the automated daily trader.
Generates 'daily_config.env'.
"""
import sys
from pathlib import Path

# Fix path to allow importing app modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Select, Switch

from app.engine import LiveTrader

CONFIG_PATH = Path(__file__).parent / "daily_config.env"


class SetupApp(App):
    CSS = """
    Screen {
        align: center middle;
    }
    .box {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    .row {
        height: 3;
        margin-bottom: 1;
        align-vertical: middle;
    }
    Label {
        width: 25;
        text-align: right;
        padding-right: 2;
    }
    Input, Select {
        width: 1fr;
    }
    #btn-save {
        width: 100%;
        margin-top: 2;
    }
    .title {
        text-align: center;
        width: 100%;
        padding-bottom: 1;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self.trader = LiveTrader()
        self.strategies = [(s, s) for s in self.trader.list_strategies()]

        # Default values
        self.default_strategy = "momentum"
        self.default_alloc = "0.1"
        self.default_long = True
        self.default_exec = False
        self.load_existing_config()

    def load_existing_config(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r") as f:
                    for line in f:
                        if "=" in line:
                            key, val = line.strip().split("=", 1)
                            if key == "TRADER_STRATEGY":
                                self.default_strategy = val
                            elif key == "TRADER_ALLOCATION":
                                self.default_alloc = val
                            elif key == "TRADER_LONG_ONLY":
                                self.default_long = val == "true"
                            elif key == "TRADER_EXECUTE":
                                self.default_exec = val == "true"
            except Exception:
                pass

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="box"):
            yield Label("Configuration Wizard", classes="title")

            with Horizontal(classes="row"):
                yield Label("Strategy:")
                yield Select(
                    self.strategies, value=self.default_strategy, id="strat", allow_blank=False
                )

            with Horizontal(classes="row"):
                yield Label("Risk Allocation (0.0-1.0):")
                yield Input(value=self.default_alloc, id="alloc")

            with Horizontal(classes="row"):
                yield Label("Long Only:")
                yield Switch(value=self.default_long, id="long")

            with Horizontal(classes="row"):
                yield Label("REAL EXECUTION:")
                yield Switch(value=self.default_exec, id="exec")

            yield Button("Save & Exit", variant="primary", id="btn-save")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.save_config()
            self.exit()

    def save_config(self):
        strat = self.query_one("#strat", Select).value
        alloc = self.query_one("#alloc", Input).value
        try:
            float(alloc)
        except ValueError:
            alloc = "0.1"

        is_long = self.query_one("#long", Switch).value
        is_exec = self.query_one("#exec", Switch).value

        content = [
            f"TRADER_STRATEGY={strat}",
            f"TRADER_ALLOCATION={alloc}",
            f"TRADER_LONG_ONLY={'true' if is_long else 'false'}",
            f"TRADER_EXECUTE={'true' if is_exec else 'false'}",
        ]

        with open(CONFIG_PATH, "w") as f:
            f.write("\n".join(content) + "\n")


if __name__ == "__main__":
    app = SetupApp()
    app.run()
