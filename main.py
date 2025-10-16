from flask import Flask, render_template, request, jsonify, send_file
import os
import PyPDF2
from io import BytesIO
import zipfile
import time
from openai import OpenAI
from chart_generator import generate_visual_report, extract_financial_data_from_report
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import re

app = Flask(__name__)

# Configuration
BATCH_SIZE = 5
MAX_PAGES_PER_PDF = 15
MAX_CONTENT_PER_FILE = 20000

print("=" * 60)
print("INITIALIZING SEGGY ANALYST")
print("=" * 60)

# Debug: Print all environment variables (without values for security)
print("Environment variables found:")
for key in os.environ:
    if 'API' in key or 'KEY' in key:
        print(f"  {key}: {'*' * len(os.environ[key])}")  # Mask the actual key

# Initialize OpenAI client
openai_key = os.environ.get('OPENAI_API_KEY')
print(f"OpenAI API Key present: {'YES' if openai_key else 'NO'}")

if openai_key:
    try:
        openai_client = OpenAI(api_key=openai_key)
        # Test the client with a simple call to verify it works
        print("✓ OpenAI client initialized successfully")
    except Exception as e:
        print(f"✗ OpenAI client initialization failed: {e}")
        openai_client = None
else:
    print("✗ OpenAI API key missing from environment variables")
    openai_client = None

print("Initialization complete\n")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        start_time = time.time()
        
        if not openai_client:
            error_msg = "OpenAI API key not configured. Please check your environment variables."
            print(f"❌ {error_msg}")
            return jsonify({'error': error_msg}), 500
        
        dd_type = request.form.get('dd_type', 'M&A Due Diligence')
        report_focus = request.form.get('report_focus', 'Financial Report')
        checklist_type = request.form.get('checklist_type', 'Simple')
        
        files = request.files.getlist('files')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files uploaded'}), 400
        
        print(f"\n{'='*60}")
        print(f"📦 PROCESSING {len(files)} FILES IN BATCHES OF {BATCH_SIZE}")
        print(f"{'='*60}\n")
        
        all_documents, uploaded_files = extract_all_files(files)
        
        if not all_documents:
            return jsonify({'error': 'Could not extract text from any files.'}), 400
        
        print(f"✓ Extracted text from {len(all_documents)} documents")
        print(f"📊 Total files to analyze: {len(all_documents)}\n")
        
        batches = create_batches(all_documents, BATCH_SIZE)
        print(f"🔄 Split into {len(batches)} batches\n")
        
        batch_reports = []
        
        for batch_num, batch in enumerate(batches, 1):
            print(f"{'='*60}")
            print(f"⚙️  PROCESSING BATCH {batch_num}/{len(batches)}")
            print(f"   Files in batch: {len(batch)}")
            print(f"{'='*60}")
            
            batch_report = process_batch(
                batch, 
                batch_num, 
                len(batches),
                dd_type, 
                report_focus
            )
            
            if batch_report:
                batch_reports.append({
                    'batch_number': batch_num,
                    'file_count': len(batch),
                    'files': [doc['filename'] for doc in batch],
                    'report': batch_report
                })
                print(f"✓ Batch {batch_num} completed\n")
            else:
                print(f"✗ Batch {batch_num} failed\n")
        
        if not batch_reports:
            return jsonify({'error': 'All batches failed to process'}), 500
        
        print(f"{'='*60}")
        print(f"🔄 SYNTHESIZING {len(batch_reports)} BATCH REPORTS")
        print(f"{'='*60}\n")
        
        final_report = synthesize_reports(
            batch_reports, 
            dd_type, 
            report_focus, 
            checklist_type,
            uploaded_files
        )
        
        print("📊 Generating charts and visualizations...")
        try:
            extracted_data = extract_financial_data_from_report(final_report)
            charts_html = generate_visual_report(final_report, extracted_data)
        except Exception as e:
            print(f"Chart generation failed: {e}")
            charts_html = ""
        
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"✅ COMPLETE! Total time: {elapsed:.2f}s")
        print(f"   Processed {len(all_documents)} files in {len(batches)} batches")
        print(f"{'='*60}\n")
        
        return jsonify({
            'report': final_report,
            'charts': charts_html,
            'uploaded_files': uploaded_files,
            'total_files': len(uploaded_files),
            'batches_processed': len(batches),
            'processing_time': f"{elapsed:.1f}s"
        })
    
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/download-pdf', methods=['POST'])
def download_pdf():
    """Generate and download PDF report"""
    try:
        data = request.get_json()
        report_text = data.get('report', '')
        
        if not report_text:
            return jsonify({'error': 'No report content provided'}), 400
        
        # Create PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, 
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor='#2c3e50',
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor='#34495e',
            spaceAfter=12,
            spaceBefore=12
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['BodyText'],
            fontSize=11,
            leading=16,
            spaceAfter=12
        )
        
        # Parse report text
        lines = report_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                story.append(Spacer(1, 0.2*inch))
                continue
            
            # Detect headers
            if line.startswith('# '):
                text = line[2:].strip()
                story.append(Paragraph(text, title_style))
            elif line.startswith('## '):
                text = line[3:].strip()
                story.append(Paragraph(text, heading_style))
            elif line.startswith('==='):
                story.append(Spacer(1, 0.1*inch))
            else:
                # Regular text
                # Escape XML special characters
                text = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(text, body_style))
        
        # Build PDF
        doc.build(story)
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='Due_Diligence_Report.pdf'
        )
    
    except Exception as e:
        print(f"PDF generation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500


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


def create_batches(documents, batch_size):
    """Split documents into batches"""
    batches = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        batches.append(batch)
    return batches


def process_batch(batch_docs, batch_num, total_batches, dd_type, report_focus):
    """Process a single batch of documents"""
    try:
        # Prepare batch documents
        batch_content = []
        for doc in batch_docs:
            batch_content.append({
                'filename': doc['filename'],
                'content': doc['content'][:15000]
            })
        
        prompt = create_batch_prompt(batch_content, batch_num, total_batches, dd_type, report_focus)
        
        report = call_openai(prompt, max_tokens=4000)
        
        return report
    
    except Exception as e:
        print(f"  ✗ Batch {batch_num} processing error: {e}")
        return None


def synthesize_reports(batch_reports, dd_type, report_focus, checklist_type, uploaded_files):
    """Combine all batch reports into a final comprehensive report"""
    try:
        synthesis_content = f"SYNTHESIS OF {len(batch_reports)} BATCH ANALYSES\n\n"
        synthesis_content += f"Total Documents Analyzed: {len(uploaded_files)}\n\n"
        
        for batch_report in batch_reports:
            synthesis_content += f"\n{'='*60}\n"
            synthesis_content += f"BATCH {batch_report['batch_number']} ANALYSIS\n"
            synthesis_content += f"Files: {', '.join(batch_report['files'][:3])}"
            if len(batch_report['files']) > 3:
                synthesis_content += f" + {len(batch_report['files']) - 3} more"
            synthesis_content += f"\n{'='*60}\n\n"
            synthesis_content += batch_report['report']
            synthesis_content += "\n\n"
        
        # Keep more context for synthesis
        if len(synthesis_content) > 35000:
            synthesis_content = synthesis_content[:35000] + "\n\n[Additional content available in batch reports...]"
        
        prompt = create_synthesis_prompt(synthesis_content, dd_type, report_focus, checklist_type, len(uploaded_files))
        
        final_report = call_openai(prompt, max_tokens=6000)
        
        header = f"""FINANCIAL DUE DILIGENCE REPORT
{'='*70}
Total Files Analyzed: {len(uploaded_files)}
Processing Method: Batch analysis ({len(batch_reports)} batches) with AI synthesis
Report Type: {dd_type} - {report_focus}
{'='*70}

"""
        
        return header + final_report
    
    except Exception as e:
        print(f"Synthesis error: {e}")
        # Fallback: combine batch reports
        combined = f"FINANCIAL DUE DILIGENCE REPORT\n{'='*70}\n"
        combined += f"Total Files Analyzed: {len(uploaded_files)}\n"
        combined += f"Processing Method: Batch analysis ({len(batch_reports)} batches)\n"
        combined += f"Report Type: {dd_type} - {report_focus}\n"
        combined += f"{'='*70}\n\n"
        
        for br in batch_reports:
            combined += f"\n## Batch {br['batch_number']} Analysis\n\n"
            combined += br['report'] + "\n\n"
        return combined


def call_openai(prompt, max_tokens=4000):
    """Make API call to OpenAI"""
    try:
        print(f"  🤖 Calling OpenAI API...")
        
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """You are a senior M&A financial analyst with 20+ years of experience at top investment banks. 

CRITICAL INSTRUCTIONS:
1. Extract ACTUAL numbers, dates, and facts from the provided documents
2. NEVER provide templates, frameworks, or placeholder text
3. If data is missing, state what's missing but still analyze what's available
4. Use specific dollar amounts, percentages, and dates from the documents
5. Reference which documents contained which data
6. Provide concrete recommendations based on actual data found
7. Always ground your analysis in the specific numbers extracted

Your analysis should be data-driven, specific, and actionable."""
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            max_tokens=max_tokens,
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        
        # Validate content has actual data
        if has_actual_content(content):
            print(f"  ✅ OpenAI success - real data found")
            return content
        else:
            print(f"  ⚠️  OpenAI returned generic content")
            return content
            
    except Exception as e:
        print(f"  ✗ OpenAI API error: {str(e)}")
        return None


def has_actual_content(text):
    """Check if text contains actual financial data vs templates"""
    number_pattern = r'\$\d+\.?\d*[MB]?|\d+\.?\d*\s*%|\d{4}[-/]\d{1,2}[-/]\d{1,2}'
    numbers_found = len(re.findall(number_pattern, text.lower()))
    
    template_phrases = [
        "you'll need to", "placeholder", "template", "framework", 
        "breakdown of how", "incorporating the specific", "this is a great"
    ]
    template_count = sum(1 for phrase in template_phrases if phrase in text.lower())
    
    return numbers_found >= 2 and template_count == 0


def create_batch_prompt(batch_docs, batch_num, total_batches, dd_type, report_focus):
    """Create detailed prompt for analyzing a single batch"""
    
    files_content = ""
    for doc in batch_docs:
        files_content += f"\n{'='*60}\nFILE: {doc['filename']}\n{'='*60}\n"
        files_content += doc['content'][:12000]
        files_content += "\n\n"
    
    return f"""ANALYZE THESE FINANCIAL DOCUMENTS FOR M&A DUE DILIGENCE:

DOCUMENTS PROVIDED:
{files_content}

EXTRACT AND ANALYZE ACTUAL FINANCIAL DATA:

REVENUE & GROWTH:
- What specific revenue numbers are mentioned? Include amounts, dates, and periods.
- Calculate growth rates between periods using actual numbers.
- Identify revenue trends and patterns.

PROFITABILITY:
- What profit margins are stated? (gross, operating, net, EBITDA)
- Extract actual percentages and amounts.
- Analyze cost structure and major expenses.

BALANCE SHEET:
- What asset amounts are listed? (current assets, fixed assets, total assets)
- What liability amounts are listed? (current liabilities, long-term debt, total liabilities)
- Calculate key ratios: current ratio, debt-to-equity.

CASH FLOW:
- What cash flow numbers are present? (operating, investing, financing)
- Analyze cash position and liquidity.

KEY FINDINGS:
List 5-7 specific findings with:
- The actual data point or figure
- Which document it came from  
- Why it matters for due diligence

RISKS IDENTIFIED:
List 3-5 specific risks found in these documents with:
- Description tied to actual data
- Severity assessment
- Source document

DATA QUALITY ASSESSMENT:
- What financial information is complete?
- What key data is missing?
- Any inconsistencies between documents?

IMPORTANT: 
- Use ONLY numbers and facts from the documents above.
- If data is not found, state "Not specified in documents".
- Reference specific documents for each data point.
- Be specific and data-driven in your analysis.
"""


def create_synthesis_prompt(batch_reports_content, dd_type, report_focus, checklist_type, total_files):
    """Create prompt for synthesizing all batch reports"""
    return f"""CREATE A COMPREHENSIVE M&A DUE DILIGENCE REPORT:

BATCH ANALYSIS RESULTS:
{batch_reports_content}

CREATE A PROFESSIONAL EXECUTIVE REPORT:

# EXECUTIVE SUMMARY
[3 paragraphs summarizing overall financial health, key value drivers, and preliminary recommendation based on ACTUAL data]

## Financial Performance Summary
- Revenue Analysis: [Specific numbers, growth rates, trends]
- Profitability: [Actual margins, profit trends]  
- Cash Flow & Liquidity: [Cash position, flow analysis]
- Balance Sheet Strength: [Asset quality, debt levels, ratios]

## Key Financial Metrics
[List 8-10 most important metrics with ACTUAL numbers and sources]

## Comprehensive Risk Assessment
[8-12 specific risks with severity, financial impact, and mitigation suggestions]

## Operational Analysis
[Business model, customer concentration, supplier dependencies based on actual data]

## Valuation Considerations
[Value drivers, quality of earnings, comparable analysis]

## Final Recommendation
[Clear Go/No-Go/Conditional Go with data-driven rationale]

## Required Additional Diligence
[Specific items needing further investigation]

CRITICAL: 
- Use ONLY the actual data from the batch reports above
- Never use placeholders or templates
- All analysis must be grounded in specific numbers found
- Reference which batches/documents provided key data
- Be specific, actionable, and professional
"""


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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
