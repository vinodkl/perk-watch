from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class Phase8Test(unittest.TestCase):
    def test_global_ask_agent_is_prominent_adaptive_and_hybrid(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "src" / "main.tsx").read_text()
        theme = (root / "web" / "src" / "theme.css").read_text()

        # The global agent owns a prominent spot before the weekly plan, then
        # becomes a compact launcher only after that hero scrolls away.
        self.assertLess(source.index("<AskDock"), source.index("<Briefing tracker={tracker}"))
        self.assertIn("IntersectionObserver", source)
        self.assertIn('className={`ask-launcher ${collapsed ? \'visible\' : \'\'}`}', source)

        # Only the global Ask rail gets the hybrid AI shell. Benefit details
        # keep their existing rail and modal scrim.
        self.assertIn('className="evidence-rail ask-rail"', source)
        self.assertNotIn('aria-label="Close Ask"', source)
        self.assertIn(".ask-rail.evidence-rail>header", theme)
        self.assertIn(".ask-rail .rail-content", theme)
        self.assertIn(".ask-rail .chat-form", theme)
        self.assertIn(".ask-agent-hero", theme)
        self.assertIn(".ask-launcher.visible", theme)

    def test_global_ask_chat_fills_rail_and_pins_composer(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "src" / "main.tsx").read_text()
        theme = (root / "web" / "src" / "theme.css").read_text()

        # The rail itself stays fixed while the conversation consumes its
        # remaining height and owns the scrolling. Suggestions and composer
        # remain at the bottom, immediately above the trust footer.
        self.assertRegex(
            theme,
            r"\.ask-rail \.rail-content\{[^}]*display:flex;[^}]*flex-direction:column;[^}]*min-height:0;[^}]*overflow:hidden",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-card\{[^}]*flex:1;[^}]*display:flex;[^}]*min-height:0",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat\{[^}]*flex:1;[^}]*display:flex;[^}]*flex-direction:column;[^}]*min-height:0",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-scroll\{[^}]*flex:1;[^}]*min-height:0;[^}]*overflow:auto",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-log\{[^}]*max-height:none;[^}]*overflow:visible;[^}]*align-content:start",
        )

        # The wallet-data note belongs with the composer, not in a separate
        # footer that consumes rail height.
        ask_rail = source[source.index("function AskRail"):source.rindex("createRoot(")]
        chat = source[source.index("function Chat"):source.index("function Markdown")]
        self.assertIn('composerNote="Amounts come from your statements, not the model."', ask_rail)
        self.assertNotIn("<footer>", ask_rail)
        self.assertIn('className="chat-composer"', chat)
        self.assertLess(chat.index("composer-note"), chat.index('className="chat-form"'))
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-composer\{[^}]*margin-left:-28px;[^}]*margin-right:-28px;[^}]*border-top:1px solid[^}]*box-shadow:0 -",
        )

    def test_global_ask_entry_points_use_light_ai_surfaces(self):
        root = Path(__file__).parents[1]
        theme = (root / "web" / "src" / "theme.css").read_text()

        # Ask stays prominent through the sidebar's violet accent family,
        # while its large surfaces remain compatible with the cream page.
        self.assertRegex(
            theme,
            r"\.ask-agent-hero\{[^}]*background:linear-gradient\(135deg,#fffdf8[^}]*#efecff[^}]*color:#2a2118",
        )
        self.assertRegex(
            theme,
            r"\.ask-dock-form input\{[^}]*background:#fffdf8;[^}]*color:#2a2118;[^}]*box-shadow:",
        )
        self.assertIn(".ask-dock-form input:focus", theme)
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-form\{[^}]*background:#f0edff;[^}]*border:1px solid",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-form input\{[^}]*background:#fffdf8;[^}]*color:#2a2118",
        )
        self.assertIn(".ask-rail .chat-form input:focus", theme)

    def test_collapsed_launcher_and_rail_composer_share_the_light_theme(self):
        root = Path(__file__).parents[1]
        theme = (root / "web" / "src" / "theme.css").read_text()

        # The compact entry point should retain the same approachable light
        # surface as the homepage Ask card instead of reverting to a dark pill.
        self.assertRegex(
            theme,
            r"\.ask-launcher\{[^}]*border:1px solid #d8d0f2;[^}]*background:linear-gradient\(135deg,#fffdf8[^}]*#efecff[^}]*color:#2a2118",
        )

        # The rail composer gets closer to the panel edges and gains enough
        # height to read as the primary action without becoming oversized.
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-composer\{[^}]*padding:12px 18px 0",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-form input\{[^}]*height:48px",
        )
        self.assertRegex(
            theme,
            r"\.ask-rail \.chat-form button\{[^}]*min-width:68px",
        )

    def test_benefit_cards_open_one_guidance_first_workspace(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "src" / "main.tsx").read_text()
        theme = (root / "web" / "src" / "theme.css").read_text()

        coupon = source[source.index("function Coupon"):source.index("function BenefitStub")]
        self.assertEqual(coupon.count("onOpen(b.benefit_id)"), 1)
        self.assertIn("Help me use", coupon)
        self.assertNotIn(">Details<", coupon)

        benefit_rail = source[source.index("function BenefitRail"):source.index("function Community")]
        self.assertIn('className="evidence-rail benefit-guide-rail"', benefit_rail)
        self.assertIn("BEST NEXT MOVE", benefit_rail)
        self.assertIn("intro={", benefit_rail)
        self.assertNotIn("afterMessages={", benefit_rail)
        self.assertNotIn("<footer>", benefit_rail)

        chat = source[source.index("function Chat"):source.index("function Markdown")]
        self.assertIn('className="chat-scroll"', chat)
        self.assertRegex(
            theme,
            r"\.benefit-guide-rail \.rail-content\{[^}]*display:flex;[^}]*overflow:hidden",
        )
        self.assertRegex(
            theme,
            r"\.benefit-guide-rail \.chat-scroll\{[^}]*flex:1;[^}]*overflow:auto",
        )
        self.assertRegex(
            theme,
            r"\.benefit-guide-rail \.chat-composer\{[^}]*flex:none;[^}]*border-top:1px solid",
        )

    def test_benefit_supporting_sections_precede_chat_and_show_toggles(self):
        root = Path(__file__).parents[1]
        source = (root / "web" / "src" / "main.tsx").read_text()
        theme = (root / "web" / "src" / "theme.css").read_text()
        benefit_rail = source[source.index("function BenefitRail"):source.index("function Community")]

        self.assertNotIn("afterMessages={", benefit_rail)
        self.assertLess(benefit_rail.index("BEST NEXT MOVE"), benefit_rail.index("Community ideas"))
        self.assertLess(benefit_rail.index("Community ideas"), benefit_rail.index("Benefit details"))
        self.assertLess(benefit_rail.index("Benefit details"), benefit_rail.index("Fine print"))
        self.assertIn('className="benefit-guide-section community-section" open', benefit_rail)
        self.assertIn('className="benefit-guide-section benefit-details"', benefit_rail)
        self.assertIn('className="benefit-guide-section fine-print"', benefit_rail)
        self.assertEqual(benefit_rail.count('className="toggle-indicator"'), 3)
        self.assertIn(".benefit-guide-section[open] .toggle-indicator", theme)

    def test_demo_builder_uses_real_preparation_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "scripts/build_demo_data.py", "--root", str(Path(temporary) / "demo-output")],
                cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["unresolved_count"], 0)

        refused = subprocess.run(
            [sys.executable, "scripts/build_demo_data.py", "--root", "demo/output"],
            cwd=Path(__file__).parents[1], text=True, capture_output=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("outside the repository", refused.stderr)


if __name__ == "__main__":
    unittest.main()
