from flask import Flask, render_template, request, jsonify, send_file
import os
import PyPDF2
from io import BytesIO
import zipfile
import time
import cohere
import requests
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

print("Initializing API clients...")

cohere_client = None
try:
    cohere_api_key = os.environ.get('COHERE_API_KEY')
    if cohere_api_key:
        cohere_client = cohere.ClientV2(api_key=cohere_api_key)
        print("✓ Cohere initialized")
except Exception as e:
    print(f"✗ Cohere failed: {e}")

openrouter_key = os.environ.get('OPENROUTER_API_KEY')
if openrouter_key:
    print("✓ OpenRouter key available")
else:
    print("✗ OpenRouter key missing - REQUIRED")

huggingface_key = os.environ.get('HUGGINGFACE_API_KEY')
if huggingface_key:
    print("✓ HuggingFace key available")

print("API initialization complete\n")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        start_time = time.time()
        
        if not openrouter_key:
            return jsonify({'error': 'OpenRouter API key not configured.'}), 500
        
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
        # Prepare batch documents with MORE content
        batch_content = []
        for doc in batch_docs:
            batch_content.append({
                'filename': doc['filename'],
                'content': doc['content'][:15000]  # Increased content
            })
        
        prompt = create_batch_prompt(batch_content, batch_num, total_batches, dd_type, report_focus)
        
        report = call_openrouter(prompt, max_tokens=4000, use_better_models=False)
        
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
        
        final_report = call_openrouter(prompt, max_tokens=6000, use_better_models=True)
        
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


def call_openrouter(prompt, max_tokens=3000, use_better_models=False):
    """Make API call to OpenRouter with improved model selection and better error handling"""
    
    if use_better_models:
        # Use better models for synthesis
        models = [
            "meta-llama/llama-3.1-70b-instruct:free",
            "google/gemini-pro-1.5-exp",
            "anthropic/claude-3.5-sonnet:free",
            "meta-llama/llama-3.1-8b-instruct:free",
        ]
    else:
        # Faster models for batch processing
        models = [
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free",
            "microsoft/phi-3-mini-128k-instruct:free",
        ]
    
    for model in models:
        try:
            print(f"  🤖 Trying model: {model}")
            
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "HTTP-Referer": "https://seggy-analyst.onrender.com",
                    "X-Title": "Seggy Analyst"
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system", 
                            "content": """CRITICAL: You are a senior M&A financial analyst. You MUST:
1. Extract ACTUAL numbers, dates, and facts from the provided documents
2. NEVER provide templates, frameworks, or placeholder text
3. If data is missing, state what's missing but still analyze what's available
4. Use specific dollar amounts, percentages, and dates from the documents
5. Reference which documents contained which data
6. Provide concrete recommendations based on actual data found

FAILURE TO EXTRACT REAL DATA WILL RESULT IN POOR PERFORMANCE."""
                        },
                        {
                            "role": "user", 
                            "content": prompt
                        }
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.1,  # Lower temperature for more factual output
                    "top_p": 0.9
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    
                    # STRICT template detection
                    template_phrases = [
                        "I can help you structure",
                        "Once you provide", 
                        "Here's a framework",
                        "This is a great framework",
                        "breakdown of how to approach",
                        "You'll need to pull from",
                        "incorporating the specific data",
                        "placeholder for",
                        "template for",
                        "framework for"
                    ]
                    
                    if any(phrase.lower() in content.lower() for phrase in template_phrases):
                        print(f"  ⚠️  {model} returned template - REJECTED")
                        continue
                    
                    # Check if content has actual numbers and analysis
                    if has_actual_content(content):
                        print(f"  ✅ {model} success - real data found")
                        return content
                    else:
                        print(f"  ⚠️  {model} returned generic content - trying next")
                        continue
                        
            elif response.status_code == 402:
                print(f"  💳 {model} - Out of credits")
                continue
            else:
                print(f"  ✗ {model} API error: {response.status_code}")
                continue
                
        except Exception as e:
            print(f"  ✗ {model} error: {str(e)[:100]}")
            continue
    
    print("  ❌ All models failed - returning error")
    return "ERROR: All AI models failed to provide actual analysis. Please try different documents or check API credits."


def has_actual_content(text):
    """Check if text contains actual financial data vs templates"""
    # Look for actual numbers, dates, specific references
    number_pattern = r'\$\d+\.?\d*[MB]?|\d+\.?\d*\s*%|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b'
    numbers_found = len(re.findall(number_pattern, text.lower()))
    
    # Look for template phrases (negative indicator)
    template_phrases = [
        "you'll need to", "placeholder", "template", "framework", 
        "breakdown of how", "incorporating the specific", "this is a great"
    ]
    template_count = sum(1 for phrase in template_phrases if phrase in text.lower())
    
    # Look for actual analysis indicators
    analysis_indicators = [
        "revenue", "profit", "margin", "cash", "debt", "assets", 
        "liabilities", "growth", "decline", "increase", "decrease"
    ]
    analysis_count = sum(1 for word in analysis_indicators if word in text.lower())
    
    return numbers_found >= 3 and template_count == 0 and analysis_count >= 5


def create_batch_prompt(batch_docs, batch_num, total_batches, dd_type, report_focus):
    """Create detailed prompt for analyzing a single batch - FIXED to prevent templates"""
    
    files_content = ""
    for doc in batch_docs:
        files_content += f"\n{'='*60}\nFILE: {doc['filename']}\n{'='*60}\n"
        files_content += doc['content'][:12000]
        files_content += "\n\n"
    
    return f"""CRITICAL: You are analyzing ACTUAL financial documents. Extract REAL data. Do NOT provide templates.

DOCUMENTS PROVIDED:
{files_content}

ANALYSIS REQUIREMENTS:

1. EXTRACT THESE ACTUAL NUMBERS FROM THE DOCUMENTS:
   - Revenue figures with years/dates: [ACTUAL $ AMOUNTS]
   - Profit margins: [ACTUAL %]
   - Assets and liabilities: [ACTUAL $ AMOUNTS] 
   - Cash flow numbers: [ACTUAL $ AMOUNTS]
   - Debt levels: [ACTUAL $ AMOUNTS]
   - Growth rates: [ACTUAL % CALCULATED FROM DATA]

2. FOR EACH NUMBER, SPECIFY:
   - Exact value found
   - Time period (year/quarter)
   - Which document it came from

3. WRITE ANALYSIS USING ACTUAL DATA:

REVENUE ANALYSIS:
- What are the actual revenue numbers found? List them with dates.
- Calculate growth rates between periods using actual numbers.
- Identify revenue trends based on actual data.

PROFITABILITY:  
- What gross/operating/net margins are stated? Use actual percentages.
- What EBITDA numbers are present? Use actual amounts.
- Analyze cost structure using actual expense numbers.

BALANCE SHEET:
- List actual asset amounts found.
- List actual liability amounts found. 
- Calculate working capital using actual numbers.
- Analyze debt levels using actual amounts.

CASH FLOW:
- What operating cash flow numbers are present?
- What investing/financing cash flow amounts are found?
- Analyze cash position using actual numbers.

KEY RISKS IDENTIFIED:
Based on ACTUAL data found, list specific risks with:
- Risk description tied to actual numbers
- Severity based on financial impact
- Source document

IMMEDIATE FINDINGS:
List 5-7 specific findings using ACTUAL numbers from the documents.

REMEMBER: 
- If data is missing, say "Data not found in documents" but still analyze what's available.
- NEVER use placeholders like [insert number] or [year].
- Use ONLY the numbers and facts present in the documents above.
- Reference specific documents for each data point.
"""


def create_synthesis_prompt(batch_reports_content, dd_type, report_focus, checklist_type, total_files):
    """Create prompt for synthesizing all batch reports - FIXED to prevent templates"""
    return f"""CRITICAL: Create a FINAL due diligence report using ONLY ACTUAL DATA from the batch analyses below. 
NO TEMPLATES. NO FRAMEWORKS. Use only the real numbers and facts provided.

BATCH ANALYSIS DATA:
{batch_reports_content}

CREATE THE FINAL REPORT WITH THIS STRUCTURE:

# EXECUTIVE SUMMARY

[3 paragraphs summarizing the ACTUAL financial situation using specific numbers found]

Overall Financial Health: [Based on actual revenue, profit, cash flow numbers]
Key Value Drivers: [Specific factors identified from actual data]
Recommendation: [Go/No-Go based on actual findings]

## Financial Performance Summary

Revenue: [ACTUAL numbers with years and growth rates calculated]
Profitability: [ACTUAL margin percentages and trends]
Cash Flow: [ACTUAL cash flow numbers and analysis]
Balance Sheet: [ACTUAL asset/liability amounts and ratios]

## Key Financial Metrics

- Revenue (Latest): $[ACTUAL AMOUNT] from [DOCUMENT]
- Gross Margin: [ACTUAL %] from [DOCUMENT]  
- Operating Margin: [ACTUAL %] from [DOCUMENT]
- Net Income: $[ACTUAL AMOUNT] from [DOCUMENT]
- Cash Position: $[ACTUAL AMOUNT] from [DOCUMENT]
- Total Debt: $[ACTUAL AMOUNT] from [DOCUMENT]

## Risk Assessment

[Based on ACTUAL data found, list 5-8 specific risks with:
- Risk description tied to actual numbers
- Severity (High/Medium/Low)
- Financial impact estimate
- Source documents]

## Operational Analysis

[Based on ACTUAL data found in documents]

## Final Recommendation & Rationale

[Specific recommendation based on actual financial data]
[3 key data points supporting the decision]
[Required next steps based on missing data]

CRITICAL REMINDERS:
- Use ONLY numbers and facts from the batch reports above
- NEVER use placeholders or templates
- If data is inconsistent, note the inconsistencies
- Reference which documents provided key data points
- All analysis must be grounded in actual numbers found
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
