from app.ingest import chunk_pages, extract_pdf_pages, extract_workbook


def test_pdf_pages_and_chunks(files):
    pages = extract_pdf_pages(files["pdf"])
    assert [p for p, _ in pages] == [1, 2, 3, 4]
    chunks = chunk_pages(pages)
    assert all(c.text and 1 <= c.page <= 4 for c in chunks)
    assert any("asbestos" in c.text.lower() and c.page == 3 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_chunks_never_cross_pages():
    chunks = chunk_pages([(1, "A. " * 400), (2, "B. " * 400)], max_chars=100)
    assert all(("A." in c.text) != ("B." in c.text) for c in chunks)


def test_workbook_tables_and_headers(files):
    tables = {t.sheet: t for t in extract_workbook(files["xlsx"])}
    assert set(tables) == {"Task Costs", "Quarterly Spend"}
    tc = tables["Task Costs"]
    assert "Total Cost ($)" in tc.headers  # title row above the header is skipped
    assert [r.label for r in tc.rows] == ["Task 1", "Task 2", "Task 3", "Task 4", "Task 5", "Total"]
    assert "Status" not in tc.numeric_headers()


def test_uncached_formulas_are_evaluated(files):
    tc = next(t for t in extract_workbook(files["xlsx"]) if t.sheet == "Task Costs")
    task3 = next(r for r in tc.rows if r.label == "Task 3")
    assert task3.cells["Total Cost ($)"].value == 85750       # =C6+D6+E6
    assert task3.cells["Total Cost ($)"].cell == "F6"
    total = next(r for r in tc.rows if r.label == "Total")
    assert total.cells["Total Cost ($)"].value == 322000      # =SUM(F4:F8)
    assert total.cells["Variance ($)"].value == 4000
