from __future__ import annotations

from pathlib import Path
from typing import Callable

from .graph.workflow import build_workflow
from .subgraphs.tool_loop import build_tool_loop


GraphFactory = Callable[[], object]


OUTPUT_DIR = Path(".")
WORKFLOW_BASENAME = "workflow_graph"
TOOL_LOOP_BASENAME = "tool_loop_graph"


def try_write_png(compiled_graph, out_path: Path) -> bool:
    try:
        png_bytes = compiled_graph.get_graph().draw_mermaid_png()
        out_path.write_bytes(png_bytes)
        return True
    except Exception as exc:
        print(f"PNG render failed for {out_path.name}: {exc}")
        return False



def try_write_svg(compiled_graph, out_path: Path) -> bool:
    try:
        draw_fn = getattr(compiled_graph.get_graph(), "draw_mermaid_svg", None)
        if draw_fn is None:
            return False
        svg_text = draw_fn()
        out_path.write_text(svg_text, encoding="utf-8")
        return True
    except Exception as exc:
        print(f"SVG render failed for {out_path.name}: {exc}")
        return False



def render_graph(graph_name: str, graph_factory: GraphFactory, output_dir: Path) -> None:
    compiled_graph = graph_factory()

    mermaid_text = compiled_graph.get_graph().draw_mermaid()
    mmd_path = output_dir / f"{graph_name}.mmd"
    png_path = output_dir / f"{graph_name}.png"
    svg_path = output_dir / f"{graph_name}.svg"

    mmd_path.write_text(mermaid_text, encoding="utf-8")
    png_ok = try_write_png(compiled_graph, png_path)
    svg_ok = try_write_svg(compiled_graph, svg_path)

    print("Generated:")
    print(f" - {mmd_path.resolve()}")
    if png_ok:
        print(f" - {png_path.resolve()}")
    if svg_ok:
        print(f" - {svg_path.resolve()}")

    print(f"\nMermaid preview for {graph_name}:\n")
    print(mermaid_text)
    print("\n" + "-" * 80 + "\n")



def main() -> None:
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    render_graph(WORKFLOW_BASENAME, build_workflow, output_dir)
    render_graph(TOOL_LOOP_BASENAME, build_tool_loop, output_dir)


if __name__ == "__main__":
    main()
