"""글자 선택이 가능한 합성 PDF만 메모리에서 만든다. 외부 파일·환자자료는 사용하지 않는다."""

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject


TEXT = """CHART_NO: T-PDF0001
PATIENT_NAME: 테스트PDF
REPORT_REF: TEST-PDF-0001
RECEIVED_DATE: 2026-11-05
REPORT_DATE: 2026-11-05
AST 52 U/L H
Hb 13.8 g/dL
HBsAg Neg
Anti-HBs Pos
Anti-HCV Neg
"""


def pdf_bytes(content: str = TEXT, *, blank: bool = False, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if not blank:
        cmap = DecodedStreamObject()
        cmap.set_data(b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
            b"/CMapName /SyntheticUCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> "
            b"endcodespacerange 1 beginbfrange <0000> <FFFF> <0000> endbfrange endcmap "
            b"CMapName currentdict /CMap defineresource pop end end")
        cid = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/CIDFontType2"), NameObject("/BaseFont"): NameObject("/MalgunGothic"),
            NameObject("/CIDSystemInfo"): DictionaryObject({NameObject("/Registry"): TextStringObject("Adobe"),
                NameObject("/Ordering"): TextStringObject("Identity"), NameObject("/Supplement"): NumberObject(0)})})
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/MalgunGothic"), NameObject("/Encoding"): NameObject("/Identity-H"),
            NameObject("/DescendantFonts"): ArrayObject([writer._add_object(cid)]),
            NameObject("/ToUnicode"): writer._add_object(cmap)})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        commands = [b"BT /F1 11 Tf 14 TL 40 790 Td"]
        for line in content.splitlines():
            commands.append(b"<" + line.encode("utf-16-be").hex().encode() + b"> Tj T*")
        commands.append(b"ET")
        stream = DecodedStreamObject()
        stream.set_data(b"\n".join(commands))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-only")
    output = BytesIO()
    writer.write(output)
    writer.close()
    return output.getvalue()
