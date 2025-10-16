from flask import Flask, render_template, request, jsonify, send_file
import os
import PyPDF2
from io import BytesIO
import zipfile
from chart_generator import generate_visual_report, extract_financial_data_from_report
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT

app = Flask(__name__)

# Configuration
MAX_PAGES_PER_PDF = 15
MAX_CONTENT_PER_FILE = 20000

print("=" * 60)
print("INITIALIZING SEGGY ANALYST (Puter.js Version)")
print("✓ Backend running - AI processing moved to frontend")
print("=" * 60)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/extract-text', methods=['POST'])
def extract_text():
    """Extract text from files for frontend AI processing"""
    try:
        files = request.files.getlist('files')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files uploaded'}), 400
        
        all_documents, uploaded_files = extract_all_files(files)
        
        if not all_documents:
            return jsonify({'error': 'Could not extract text from any files.'}), 400
        
        print(f"✓ Extracted text from {len(all_documents)} documents")
        
        return jsonify({
            'documents': all_documents,
            'uploaded_files': uploaded_files,
            'total_files': len(uploaded_files)
        })
    
    except Exception as e:
        print(f"❌ Text extraction error: {str(e)}")
        return jsonify({'error': f'Text extraction failed: {str(e)}'}), 500

@app.route('/generate-charts', methods=['POST'])
def generate_charts():
    """Generate charts from report text"""
    try:
        data = request.get_json()
        report_text = data.get('report', '')
        
        if not report_text:
            return jsonify({'error': 'No report content provided'}), 400
        
        extracted_data = extract_financial_data_from_report(report_text)
        charts_html = generate_visual_report(report_text, extracted_data)
        
        return jsonify({
            'charts': charts_html,
            'success': True
        })
        
    except Exception as e:
        print(f"Chart generation error: {e}")
        return jsonify({'error': f'Chart generation failed: {str(e)}'}), 500

# Keep all the existing file processing functions (extract_all_files, extract_zip_file, extract_pdf_from_bytes, extract_pdf_text)
# Keep the download-pdf function exactly as is

def extract_all_files(files):
    """Extract text from all uploaded files"""
    all_documents = []
    uploaded_files = []
    
    for file in files:
        if file.filename == '':
            continue
        
        if file.filename.lower().endswith('.zip'):
            extracted_files = extract_zip_file(file)
            for extracted_name, extracted_content in extracted_files:
                uploaded_files.append(extracted_name)
                if extracted_content:
                    all_documents.append({
                        'filename': extracted_name,
                        'content': extracted_content[:MAX_CONTENT_PER_FILE]
                    })
        else:
            filename = file.filename
            uploaded_files.append(filename)
            
            pdf_text = extract_pdf_text(file)
            if pdf_text:
                all_documents.append({
                    'filename': filename,
                    'content': pdf_text[:MAX_CONTENT_PER_FILE]
                })
    
    return all_documents, uploaded_files

def extract_zip_file(zip_file):
    """Extract PDF files from ZIP archive"""
    extracted_files = []
    try:
        zip_bytes = zip_file.read()
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zip_ref:
            for file_info in zip_ref.filelist:
                if file_info.is_dir() or not file_info.filename.lower().endswith('.pdf'):
                    continue
                try:
                    pdf_bytes = zip_ref.read(file_info)
                    pdf_text = extract_pdf_from_bytes(pdf_bytes)
                    clean_filename = os.path.basename(file_info.filename)
                    extracted_files.append((clean_filename, pdf_text))
                except Exception as e:
                    print(f"Error extracting {file_info.filename}: {e}")
        return extracted_files
    except Exception as e:
        print(f"ZIP processing error: {e}")
        return []

def extract_pdf_from_bytes(pdf_bytes):
    """Extract text from PDF bytes"""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        text = ""
        page_count = min(MAX_PAGES_PER_PDF, len(pdf_reader.pages))
        
        for page_num in range(page_count):
            page = pdf_reader.pages[page_num]
            text += page.extract_text() + "\n"
            if len(text) > 30000:
                break
        
        return text.strip()
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return None

def extract_pdf_text(file):
    """Extract text from PDF file"""
    try:
        file_bytes = file.read()
        return extract_pdf_from_bytes(file_bytes)
    except Exception as e:
        print(f"File read error: {e}")
        return None

# Keep the download-pdf function exactly as before
@app.route('/download-pdf', methods=['POST'])
def download_pdf():
    # ... keep the exact same implementation you have now

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
