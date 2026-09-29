"""Build the reviewable DineIQ project report from verified repository evidence."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "documentation" / "submission" / "DineIQ_Project_Report.docx"
FIGURES = ROOT / "handoff_exports" / "docx_qa" / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)

INK = "19312D"
GREEN = "18493C"
ORANGE = "D97D20"
PALE = "F4F5F1"
BLUE = "E8F1F6"
GRAY = "66736F"
LINE = "CCD5CF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    base = Path("C:/Windows/Fonts")
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(base / name), size)


def rounded(draw, box, label, fill=PALE, outline=LINE, size=25):
    draw.rounded_rectangle(box, radius=18, fill=f"#{fill}", outline=f"#{outline}", width=2)
    lines = label.split("\n")
    widths = [draw.textbbox((0, 0), line, font=font(size, True))[2] for line in lines]
    y = (box[1] + box[3] - len(lines) * (size + 8)) / 2
    for line, width in zip(lines, widths):
        draw.text(((box[0] + box[2] - width) / 2, y), line, font=font(size, True), fill=f"#{INK}")
        y += size + 8


def arrow(draw, start, end, color=GREEN, width=5):
    draw.line((start, end), fill=f"#{color}", width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 18
    for offset in (-0.52, 0.52):
        pt = (end[0] - length * math.cos(angle + offset), end[1] - length * math.sin(angle + offset))
        draw.line((end, pt), fill=f"#{color}", width=width)


def canvas(name: str, height: int = 700):
    image = Image.new("RGB", (1800, height), "white")
    return image, ImageDraw.Draw(image), FIGURES / f"{name}.png"


def diagram_architecture():
    image, draw, path = canvas("architecture", 710)
    rounded(draw, (70, 75, 440, 175), "Browser and role scoped UI", BLUE)
    rounded(draw, (540, 75, 910, 175), "Django on Windows\nuv runtime", PALE)
    rounded(draw, (1040, 75, 1420, 175), "PostgreSQL\nDocker container", PALE)
    arrow(draw, (440, 125), (540, 125))
    arrow(draw, (910, 125), (1040, 125))
    rounded(draw, (70, 320, 440, 420), "Synthetic generator\nraw CSV and JSON", PALE)
    rounded(draw, (540, 320, 910, 420), "Spark master and worker\nDocker Hub runtime", BLUE)
    rounded(draw, (1040, 320, 1420, 420), "Accepted Parquet\nquarantine and reports", PALE)
    arrow(draw, (440, 370), (540, 370))
    arrow(draw, (910, 370), (1040, 370))
    rounded(draw, (540, 550, 910, 650), "Independent Python\nmodel pipeline", PALE)
    arrow(draw, (1040, 410), (910, 590))
    arrow(draw, (910, 600), (1040, 440))
    arrow(draw, (1220, 320), (760, 175))
    draw.text((1470, 345), "Redis is provisioned.\nNo app queue is claimed.", font=font(23), fill=f"#{GRAY}")
    image.save(path)
    return path


def diagram_flow():
    image, draw, path = canvas("data_flow", 720)
    boxes = [
        ((50, 90, 300, 200), "Raw tables"),
        ((390, 90, 670, 200), "Spark schema\nand quality"),
        ((760, 90, 1040, 200), "Accepted\nParquet"),
        ((1130, 90, 1420, 200), "Spark SQL\nand features"),
        ((1130, 330, 1420, 440), "Spark model\npredictions"),
        ((760, 330, 1040, 440), "Python model\npredictions"),
        ((390, 330, 670, 440), "Keyed comparison\n17,180 records"),
        ((50, 330, 300, 440), "Quarantine\nwith reasons"),
        ((390, 560, 670, 670), "Saved evidence"),
        ((760, 560, 1040, 670), "Scoped Django\nreports and UI"),
    ]
    for box, label in boxes:
        rounded(draw, box, label, BLUE if "model" in label or "comparison" in label else PALE)
    for a, b in [((300, 145), (390, 145)), ((670, 145), (760, 145)), ((1040, 145), (1130, 145)),
                 ((530, 200), (175, 330)), ((900, 200), (900, 330)), ((1275, 200), (1275, 330)),
                 ((1130, 385), (670, 385)), ((760, 385), (670, 385)), ((530, 440), (530, 560)),
                 ((670, 615), (760, 615))]:
        arrow(draw, a, b)
    image.save(path)
    return path


def diagram_entities():
    image, draw, path = canvas("entities", 700)
    nodes = [
        ((100, 65, 440, 160), "Restaurant"), ((580, 65, 920, 160), "Order"),
        ((1050, 65, 1390, 160), "Customer and channel"),
        ((580, 270, 920, 365), "Order item"),
        ((100, 485, 440, 580), "Menu item and category"),
        ((580, 485, 920, 580), "Rating and promotion"),
    ]
    for box, label in nodes:
        rounded(draw, box, label, BLUE if label in ("Restaurant", "Order", "Order item") else PALE)
    for a, b in [((440, 113), (580, 113)), ((1050, 113), (920, 113)), ((750, 160), (750, 270)),
                 ((580, 318), (360, 485)), ((750, 365), (750, 485))]:
        arrow(draw, a, b)
    draw.text((80, 630), "Simplified relationships; field types and constraints are in the data dictionary and Django migrations.", font=font(22), fill=f"#{GRAY}")
    image.save(path)
    return path


def diagram_access():
    image, draw, path = canvas("roles", 610)
    labels = [("Administrator", 60), ("Analyst", 410), ("Regional manager", 760), ("Restaurant manager", 1110)]
    for label, x in labels:
        rounded(draw, (x, 70, x + 300, 160), label, PALE, size=22)
        arrow(draw, (x + 150, 160), (900, 305))
    rounded(draw, (680, 305, 1120, 405), "Authenticate and\nresolve location scope", BLUE)
    for label, x in [("Dashboards", 80), ("What if", 440), ("Reports and CSV", 800), ("Recommendations", 1220)]:
        rounded(draw, (x, 510, x + 290, 590), label, PALE, size=22)
        arrow(draw, (900, 405), (x + 145, 510))
    image.save(path)
    return path


def diagram_activity():
    image, draw, path = canvas("activity", 390)
    labels = ["Validate input", "Split accepted\nand quarantine", "Historical features", "Train and\nvalidate", "Held out test", "Review only\nevidence"]
    for i, label in enumerate(labels):
        x = 45 + i * 290
        rounded(draw, (x, 140, x + 245, 255), label, BLUE if i in (1, 4) else PALE, size=22)
        if i:
            arrow(draw, (x - 45, 196), (x, 196))
    draw.text((80, 325), "Failed count, lineage or consistency checks stop publication and preserve evidence.", font=font(25), fill=f"#{INK}")
    image.save(path)
    return path


def diagram_sequence():
    image, draw, path = canvas("sequence", 620)
    xs = [150, 520, 890, 1260, 1630]
    labels = ["User", "Django", "Scope service", "PostgreSQL", "Saved evidence"]
    for x, label in zip(xs, labels):
        rounded(draw, (x - 125, 30, x + 125, 100), label, BLUE, size=21)
        draw.line((x, 100, x, 570), fill=f"#{LINE}", width=3)
    steps = [
        (0, 1, 150, "Report request"), (1, 2, 225, "Resolve permitted locations"),
        (2, 3, 300, "Read grants"), (3, 2, 360, "Scope"),
        (1, 4, 435, "Read validated scoped output"), (4, 1, 495, "Values and limits"),
        (1, 0, 550, "Download or unavailable response"),
    ]
    for src, dst, y, label in steps:
        arrow(draw, (xs[src], y), (xs[dst], y), ORANGE if src > dst else GREEN, 3)
        draw.text((min(xs[src], xs[dst]) + 13, y - 31), label, font=font(18), fill=f"#{INK}")
    image.save(path)
    return path


def set_cell_fill(cell, value):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), value)
    tc_pr.append(shd)


def add_table(doc, headers, rows, widths=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, title in enumerate(headers):
        table.rows[0].cells[i].text = str(title)
        set_cell_fill(table.rows[0].cells[i], GREEN)
        for run in table.rows[0].cells[i].paragraphs[0].runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
    for r, data in enumerate(rows):
        cells = table.add_row().cells
        for i, value in enumerate(data):
            cells[i].text = str(value)
            cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if r % 2:
                set_cell_fill(cells[i], "F4F6F5")
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                for run in p.runs:
                    run.font.size = Pt(8.5)
    if widths:
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Inches(width)
    doc.add_paragraph()
    return table


def add_figure(doc, path, caption):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Inches(6.9))
    cap = doc.add_paragraph(caption)
    cap.style = "Caption"
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER


doc = Document()
sec = doc.sections[0]
sec.page_width = Inches(8.5)
sec.page_height = Inches(11)
sec.left_margin = Inches(0.8)
sec.right_margin = Inches(0.8)
sec.top_margin = Inches(0.72)
sec.bottom_margin = Inches(0.72)

styles = doc.styles
styles["Normal"].font.name = "Aptos"
styles["Normal"].font.size = Pt(10.5)
styles["Normal"].font.color.rgb = RGBColor.from_string(INK)
styles["Normal"].paragraph_format.space_after = Pt(7)
for name, size, before, after in [("Title", 25, 0, 16), ("Heading 1", 15, 15, 6), ("Heading 2", 11.5, 10, 4)]:
    style = styles[name]
    style.font.name = "Aptos Display" if name == "Title" else "Aptos"
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.keep_with_next = True
    p_pr = style.element.get_or_add_pPr()
    border = p_pr.find(qn("w:pBdr"))
    if border is not None:
        p_pr.remove(border)
styles["Subtitle"].font.name = "Aptos"
styles["Subtitle"].font.size = Pt(11)
styles["Subtitle"].font.italic = False
styles["Subtitle"].font.color.rgb = RGBColor(0, 0, 0)
styles["Caption"].font.size = Pt(8.5)
styles["Caption"].font.color.rgb = RGBColor.from_string(GRAY)

doc.add_paragraph("DineIQ Analytics Project Report", style="Title")
doc.add_paragraph("Restaurant intelligence implementation and evaluation", style="Subtitle")
doc.add_paragraph("29 September 2026  |  Student project submission draft  |  Human review pending")
doc.add_paragraph(
    "DineIQ combines a Django interface with synthetic restaurant data, Spark processing, and an independently built Python demand pipeline. "
    "This report explains the implemented architecture, analytical results, test evidence, and remaining submission work. "
    "Its findings describe a controlled demonstration, not a deployed restaurant decision system."
)

doc.add_heading("Purpose and scope", level=1)
doc.add_paragraph(
    "Restaurant managers need to compare sales with contribution, customer behavior and waste across locations. A popular dish can still lose money, "
    "and aggregate network results can hide a branch-specific problem. The application organizes those signals into scoped dashboards, reports, "
    "review candidates and bounded what-if estimates. It does not automate pricing, purchasing or customer outreach."
)
doc.add_paragraph(
    "The present data is synthetic. The generated historical period is January 2025 through June 2026; later saved forecast months are estimates. "
    "Direct contribution means revenue less historical direct item cost, not net profit. Live POS ingestion is outside the present scope."
)

doc.add_heading("System architecture", level=1)
doc.add_paragraph(
    "Django and uv run on Windows. Docker Compose supplies PostgreSQL, Redis and a Spark standalone cluster. "
    "The published Docker Hub image packages the Spark 3.5.9 runtime only; it does not contain the Django web server, database or generated data. "
    "Spark and Python batch jobs write validated evidence before the web layer reads it. Redis is provisioned, but an application job queue is not verified."
)
add_figure(doc, diagram_architecture(), "Figure 1  Deployment and system architecture")
doc.add_paragraph(
    "The shared mounted folders hold raw sources, accepted and rejected Parquet, stage reports and model artifacts. "
    "A dashboard request does not retrain a model. PostgreSQL domain edits do not automatically rebuild the analytical snapshot."
)

doc.add_heading("Data preparation and quality", level=1)
doc.add_paragraph(
    "The seeded full profile creates 350,000 reference orders, 1,050,000 lines and 60,000 customers across 24 restaurants. "
    "Controlled defects exercise quality rules. Exactly 16,065 injected defects appear in the generation ledger; quarantine counts differ because "
    "invalid parent records can also invalidate children. Spark accepted 3,995,252 records and quarantined 21,796 in the verified full run."
)
add_figure(doc, diagram_flow(), "Figure 2  Processing and analytical data flow")
doc.add_paragraph(
    "Explicit schemas and key, date, numeric, relationship and business-rule checks govern ingestion. Rejected records retain reasons. "
    "The generator's clean reference is used to validate the experiment, not as a model-training shortcut. Chronological features stop at each training cutoff."
)
add_figure(doc, diagram_entities(), "Figure 3  Simplified restaurant data relationships")

doc.add_heading("Analytical methods", level=1)
doc.add_paragraph(
    "Menu classes compare revenue, contribution, demand and supporting evidence with category peers. Profit Driver, Volume Driver, "
    "Hidden Opportunity and Low Performer are transparent business-rule classes, not a fitted classification model. "
    "Customer analysis includes RFM scores, segments and complete-basket associations. Forecasts estimate accepted sold portions at item, location and month grain."
)
doc.add_paragraph(
    "Other evidence covers wastage, price transitions, promotions, ratings, anomalies, location and channel comparisons, and churn review signals. "
    "Recommendations point to evidence and priority; they do not claim causal financial benefit. What-if results are simulated estimates based on bounded user assumptions."
)
add_figure(doc, diagram_activity(), "Figure 4  Model preparation and publication activity")

doc.add_heading("Model evaluation", level=1)
doc.add_paragraph(
    "Spark MLlib evaluated linear regression, decision tree and random forest. The separate Python pipeline rebuilt features from the accepted source "
    "and selected Extra Trees after comparison with Ridge. Both estimate next-month accepted sold portions. "
    "Training targets cover May to December 2025, validation January to February 2026, and held-out testing March to June 2026."
)
add_table(doc, ["Held out measure", "Spark linear", "Python Extra Trees", "Recent demand baseline"], [
    ("Records", "17,180", "17,180", "17,180"),
    ("MAE in portions", "9.043", "8.785", "9.422"),
    ("RMSE in portions", "41.380", "41.163", "41.158"),
    ("WAPE", "46.67%", "45.34%", "48.62%"),
], [2.1, 1.45, 1.8, 1.55])
doc.add_paragraph(
    "The pipelines agree within max(2 portions, 20% of actual quantity) on 15,239 of 17,180 held-out records, or 88.70%. "
    "Agreement is not accuracy. Both models improve MAE against the recent-demand baseline but do not beat its RMSE. "
    "June 2026's demand shift materially increases error. The SRS accuracy and F1 targets are not established by this regression experiment."
)
doc.add_paragraph(
    "The separate monthly wastage-risk model achieved held-out ROC-AUC about 0.547 and average precision about 0.265; its discrimination is weak. "
    "Those scores support cautious review only, not automated stock decisions."
)

doc.add_heading("Application behavior and access", level=1)
doc.add_paragraph(
    "Authenticated administrators, analysts, regional managers and restaurant managers use server-side role and location checks. "
    "Manager scopes require explicit grants. Users can inspect dashboards, evidence, recommendations, reports and CSV exports according to their permissions. "
    "Account creation and location assignment are managed in the application; Django superuser privilege remains separate."
)
add_figure(doc, diagram_access(), "Figure 5  Business roles and scoped use cases")
doc.add_paragraph(
    "Report downloads read saved evidence, resolve location scope and return either scoped results or an unavailable response. "
    "The request path has no retraining step and does not claim an audit event that has not been verified."
)
add_figure(doc, diagram_sequence(), "Figure 6  Scoped report request sequence")

doc.add_heading("Testing and reproducibility", level=1)
doc.add_paragraph(
    "The latest focused local verification passed 94 Django account and restaurant tests and five frontend navigation and clock tests. "
    "The Spark 3.5.9 Docker image passed a spark-submit version smoke test. Earlier submission evidence records 60 Python pipeline tests and 11 generator tests; "
    "those older results should be rerun against the final code before sign-off."
)
doc.add_paragraph(
    "A public GitHub repository contains source and execution instructions. The Spark runtime is published as "
    "alirazazulfiqar/sfc-databricks:latest with registry digest "
    "sha256:727c3a55ede62a3080672efb79c8e2e7df1e7b1bf13a52e5297ec4bd6741317d. "
    "Generated data, model binaries and most stage outputs are ignored by Git and require a separately reviewed artifact handoff or regeneration."
)

doc.add_heading("Known limitations and submission work", level=1)
for item in [
    "The project does not yet demonstrate five-million-line load performance, 99 percent uptime, or a defined prediction response-time target.",
    "Application-wide audit events, model identifier propagation, persistent result metadata and an in-app Spark job monitor need completion or explicit acceptance verification.",
    "Fresh hidden-data rehearsal and clean-machine installation remain open. The published Docker image is a Spark runtime, not a public web deployment.",
    "The SRS demonstration MP4, published technical blog, final presentation, evaluator access arrangement and real team review records need human completion.",
]:
    doc.add_paragraph(item, style="List Bullet")

doc.add_heading("Source and evidence guide", level=1)
doc.add_paragraph(
    "The repository README documents installation, Docker Hub usage and GitHub delivery. "
    "documentation/submission/requirements_traceability.md maps requirements to evidence, while "
    "dual_pipeline_report.md, test_evidence.md and evaluator_guide.md provide details behind this report. "
    "The original DineIQ SRS governs the final acceptance review. All claims here should be checked against the shared evidence bundle before submission."
)
doc.add_heading("Submission deliverables", level=1)
add_table(doc, ["SRS section", "Evidence and remaining action"], [
    ("01 Project report", "This DOCX; human review and approval pending"),
    ("02 Source code", "Public GitHub source; review contribution claims"),
    ("03 Big Data dataset", "Local synthetic data; distribution and checksums pending"),
    ("04 Spark processing", "Code and saved reports; collect final logs"),
    ("05 Spark MLlib", "Model and report; artifact distribution pending"),
    ("06 Python models", "Models and reports; artifact distribution pending"),
    ("07 Dual comparison", "17,180 row evidence; include CSV in handoff"),
    ("08 Intelligence report", "Web reports; reviewed business report pending"),
    ("09 Tests", "Automated evidence; final acceptance rerun pending"),
    ("10 Installation", "README and evaluator guide; clean machine test pending"),
    ("11 Execution", "Stage guides; end to end rehearsal pending"),
    ("12 GitHub", "Public repository pushed"),
    ("13 Deployment", "Spark image published; public web deployment not claimed"),
    ("14 Demonstration video", "Mandatory MP4 pending"),
    ("15 Technical blog", "Published reviewed article pending"),
    ("16 AI declaration", "Recorded usage; human verification pending"),
    ("17 Final checklist", "Draft checklist; final sign off pending"),
], [1.65, 5.2])

doc.core_properties.title = "DineIQ Analytics Project Report"
doc.core_properties.subject = "System design, data processing, model evaluation and delivery status"
doc.core_properties.keywords = "DineIQ, Django, Spark, Python, restaurant analytics"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUTPUT)
print(OUTPUT)
