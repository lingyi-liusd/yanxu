"""Actual, synthetic document bytes; no personal data or model calls."""
import io
import zipfile
from xml.sax.saxutils import escape
from document_worker import pdf_library


def pdf_bytes(lines=('SYNTHETIC_FAIL UNKNOWN NOT_RUN',), blank=False, encrypted=False, pages=None):
    pdf=pdf_library()
    from pypdf.generic import DictionaryObject, NameObject, NumberObject, DecodedStreamObject
    writer=pdf.PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
        NameObject('/BaseFont'):NameObject('/Helvetica')})
    font_ref=writer._add_object(font)
    for index in range(pages if pages is not None else len(lines)):
        page=writer.add_blank_page(width=600,height=800)
        if not blank and index<len(lines) and lines[index]:
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font_ref})})
            stream=DecodedStreamObject()
            value=lines[index].replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
            stream.set_data(('BT /F1 12 Tf 40 740 Td ('+value+') Tj ET').encode('ascii'))
            page[NameObject('/Contents')]=writer._add_object(stream)
    if encrypted:writer.encrypt('synthetic-password')
    output=io.BytesIO();writer.write(output);return output.getvalue()


def docx_bytes(paragraphs=('合成资料：失败保留；Windows未测试。',), extra=None, xml=None):
    body=''.join('<w:p><w:r><w:t>'+escape(p)+'</w:t></w:r></w:p>' for p in paragraphs)
    document=xml or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'</w:body></w:document>'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr('word/document.xml',document)
        for name,value in (extra or {}).items():archive.writestr(name,value)
    return output.getvalue()
