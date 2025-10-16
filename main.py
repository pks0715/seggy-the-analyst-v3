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
MAX_PAGES_PER_PDF = 15  # Increased from 10
MAX_CONTENT_PER_FILE = 20000  # Increased from 15000

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

openai_key = os.environ.get('OPENAI_API_KEY')
if openai_key:
    print("✓ OpenAi key available")

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
                'content': doc['content'][:12000]  # Increased content
            })
        
        prompt = create_batch_prompt(batch_content, batch_num, total_batches, dd_type, report_focus)
        
        report = call_openrouter(prompt, max_tokens=3000, use_better_models=True)
        
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
        
        # Limit but keep more context
        if len(synthesis_content) > 30000:
            synthesis_content = synthesis_content[:30000] + "\n\n[Additional content available in batch reports...]"
        
        prompt = create_synthesis_prompt(synthesis_content, dd_type, report_focus, checklist_type, len(uploaded_files))
        
        final_report = call_openrouter(prompt, max_tokens=5000, use_better_models=True)
        
        header = f"""{'='*70}
FINANCIAL DUE DILIGENCE REPORT
{'='*70}
Total Files Analyzed: {len(uploaded_files)}
Processing Method: Batch analysis ({len(batch_reports)} batches) with AI synthesis
Report Type: {dd_type} - {report_focus}
{'='*70}

"""
        
        return header + final_report
    
    except Exception as e:
        print(f"Synthesis error: {e}")
        combined = "# FINANCIAL DUE DILIGENCE REPORT\n\n"
        for br in batch_reports:
            combined += f"\n## Batch {br['batch_number']} Analysis\n\n"
            combined += br['report'] + "\n\n"
        return combined


def call_openrouter(prompt, max_tokens=3000, use_better_models=False):
    """Make API call to OpenRouter with improved model selection"""
    
    if use_better_models:
        # Use better models for synthesis
        models = [
            "meta-llama/llama-3.1-70b-instruct:free",
            "google/gemini-pro-1.5-exp",
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free",
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
                        {"role": "system", "content": "You are a senior M&A financial analyst with 20 years of investment banking experience. You analyze financial documents and extract concrete data, numbers, and trends. Never provide templates or frameworks - always provide actual analysis with specific figures."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3  # Lower temperature for more factual output
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    # Validate it's not a template response
                    if "I can help you structure" in content or "Once you provide" in content:
                        print(f"  ⚠️  {model} returned template, trying next model...")
                        continue
                    return content
            elif response.status_code == 402:
                print(f"  💳 Out of credits - add funds at https://openrouter.ai/credits")
        except Exception as e:
            print(f"  ✗ {model} error: {str(e)[:100]}")
            continue
    
    return "Error: All models failed or returned templates"


def create_batch_prompt(batch_docs, batch_num, total_batches, dd_type, report_focus):
    """Create detailed prompt for analyzing a single batch"""
    
    files_content = ""
    for doc in batch_docs:
        files_content += f"\n{'='*60}\nFILE: {doc['filename']}\n{'='*60}\n"
        files_content += doc['content'][:10000]  # More content
        files_content += "\n\n"
    
    return f"""You are analyzing BATCH {batch_num} of {total_batches} for an M&A due diligence.

CRITICAL INSTRUCTION: Extract ACTUAL DATA from the documents. Do NOT provide templates or frameworks. 
I need REAL NUMBERS, REAL DATES, REAL TRENDS from the text below.

DOCUMENT CONTENTS:
{files_content}

Analyze these documents and provide SPECIFIC, DATA-DRIVEN findings:

## FINANCIAL DATA EXTRACTED

### Revenue & Growth
- Extract actual revenue figures with years
- Calculate growth rates between periods
- Identify revenue by segment if available
- Note any seasonality patterns

### Profitability Analysis  
- Extract gross margin, operating margin, net margin (actual %)
- Calculate EBITDA if income statement data present
- Identify cost structure and major expense categories
- Note any margin trends

### Balance Sheet Items
- Total assets, current assets (actual $amounts)
- Total liabilities, current liabilities
- Equity position
- Working capital calculation
- Debt levels and terms

### Cash Flow Observations
- Operating cash flow figures
- CapEx spending
- Free cash flow calculation
- Cash position

## KEY FINDINGS FROM DOCUMENTS

List 5-7 specific findings with:
- The actual data point or figure
- Which document it came from
- Why it matters for due diligence

## RISKS IDENTIFIED

List 3-5 risks found in these documents with:
- Description of the risk
- Severity: High/Medium/Low
- Which document revealed it
- Potential financial impact

## DATA QUALITY

- What financial information is present?
- What's missing that we'd expect?
- Any inconsistencies between documents?

REMEMBER: Extract REAL data. If a document shows "$500M revenue in 2023", write that exact figure. 
If you see "15% gross margin", state that number. Do NOT write "I need the text to analyze" - 
the text is provided above. Extract what's actually there.
"""


def create_synthesis_prompt(batch_reports_content, dd_type, report_focus, checklist_type, total_files):
    """Create prompt for synthesizing all batch reports"""
    return f"""You are creating the FINAL comprehensive due diligence report by synthesizing {total_files} analyzed documents.

CRITICAL: This must be a complete, professional report with ACTUAL DATA extracted from the batch analyses below.
Do NOT provide templates or placeholders. Use the real numbers, dates, and findings from the batches.

BATCH ANALYSIS RESULTS:
{batch_reports_content}

Create a unified, executive-ready M&A due diligence report:

# EXECUTIVE SUMMARY

Provide a 3-paragraph executive summary covering:
- Overall financial health assessment
- Key value drivers identified
- Critical decision factors
- Go/No-Go preliminary recommendation with rationale

## Key Findings (5-7 Bullet Points)

List the most important findings with ACTUAL numbers:
- Revenue: [actual $ figure and growth %]
- Profitability: [actual margins in %]
- Cash position: [actual $ amount]
- Debt levels: [actual $ and ratios]
- Key risks identified
- Valuation drivers

# CONSOLIDATED FINANCIAL ANALYSIS

## Revenue Trends and Growth
- Historical revenue figures (actual $) across all periods found
- Year-over-year growth rates (calculate from data)
- Revenue by segment/geography if available
- Analysis of sustainability and quality

## Profitability Metrics
- Gross margin: [%] 
- Operating margin: [%]
- EBITDA margin: [%]
- Net margin: [%]
- Trend analysis and peer comparison if data available

## Balance Sheet Summary
- Total assets: [$]
- Current assets: [$]
- Total liabilities: [$]
- Equity: [$]
- Key ratios: Current ratio, Debt/Equity, etc.
- Working capital position

## Cash Flow Assessment
- Operating cash flow: [$]
- Free cash flow: [$]
- Cash conversion analysis
- CapEx trends
- Cash position and runway

# COMPREHENSIVE RISK ASSESSMENT

List 8-12 risks identified across all documents:

For each risk:
1. Risk description (specific, not generic)
2. Severity: High/Medium/Low
3. Financial impact estimate
4. Source document(s)
5. Mitigation considerations

# OPERATIONAL HIGHLIGHTS

- Business model analysis
- Customer concentration (if data available)
- Supplier dependencies (if data available)
- Key contracts and commitments
- Competitive positioning

# VALUATION CONSIDERATIONS

- Key value drivers (be specific based on business model)
- Quality of earnings assessment
- Normalized EBITDA adjustments needed
- Comparable multiples if industry data available
- Value creation opportunities

# FINAL RECOMMENDATION

## Go/No-Go Decision
Provide clear recommendation: GO / NO-GO / CONDITIONAL GO

## Rationale (2-3 paragraphs)
- Support decision with specific financial data
- Reference key findings and risks
- Discuss value vs risk tradeoff

## Suggested Price Range (if applicable)
- Fair value estimate based on analysis
- Key assumptions
- Adjustment factors

## Required Additional Diligence
List 5-7 specific items that need deeper investigation:
- Missing financial data to obtain
- Risks to validate further
- Operational areas to examine
- Legal/regulatory items to verify

## Deal-Breaker Issues
List any critical issues that would prevent deal completion

---

CRITICAL REMINDERS:
- Use ACTUAL data from batch reports - no placeholders
- Include specific $ amounts and % where available  
- Reference which documents provided key data
- Be specific, not generic
- This is the final report - make it complete and actionable
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
