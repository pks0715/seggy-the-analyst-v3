from flask import Flask, render_template, request, jsonify
import os
import PyPDF2
from io import BytesIO
import zipfile
import time
import cohere
import requests
from chart_generator import generate_visual_report, extract_financial_data_from_report

app = Flask(__name__)

# Configuration
BATCH_SIZE = 5  # Process 5 files at a time
MAX_PAGES_PER_PDF = 10  # Read only first 10 pages per PDF
MAX_CONTENT_PER_FILE = 15000  # 15KB per file

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
        
        # STEP 1: Extract text from ALL files first
        all_documents, uploaded_files = extract_all_files(files)
        
        if not all_documents:
            return jsonify({'error': 'Could not extract text from any files.'}), 400
        
        print(f"✓ Extracted text from {len(all_documents)} documents")
        print(f"📊 Total files to analyze: {len(all_documents)}\n")
        
        # STEP 2: Split documents into batches
        batches = create_batches(all_documents, BATCH_SIZE)
        print(f"🔄 Split into {len(batches)} batches\n")
        
        # STEP 3: Process each batch and generate mini-reports
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
        
        # STEP 4: Synthesize all batch reports into final report
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
        
        # STEP 5: Generate charts from final report
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
                'summary': doc['content'][:2000],
                'content': doc['content'][:8000]
            })
        
        # Generate report for this batch
        prompt = create_batch_prompt(batch_content, batch_num, total_batches, dd_type, report_focus)
        
        report = call_openrouter(prompt, max_tokens=2000)  # Smaller reports per batch
        
        return report
    
    except Exception as e:
        print(f"  ✗ Batch {batch_num} processing error: {e}")
        return None


def synthesize_reports(batch_reports, dd_type, report_focus, checklist_type, uploaded_files):
    """Combine all batch reports into a final comprehensive report"""
    try:
        # Prepare synthesis content
        synthesis_content = f"SYNTHESIS OF {len(batch_reports)} BATCH ANALYSES\n\n"
        synthesis_content += f"Total Documents Analyzed: {len(uploaded_files)}\n\n"
        
        for batch_report in batch_reports:
            synthesis_content += f"\n{'='*60}\n"
            synthesis_content += f"BATCH {batch_report['batch_number']} - {batch_report['file_count']} FILES\n"
            synthesis_content += f"Files: {', '.join(batch_report['files'])}\n"
            synthesis_content += f"{'='*60}\n\n"
            synthesis_content += batch_report['report']
            synthesis_content += "\n\n"
        
        # Limit synthesis content
        if len(synthesis_content) > 20000:
            synthesis_content = synthesis_content[:20000] + "\n\n[Content truncated...]"
        
        prompt = create_synthesis_prompt(synthesis_content, dd_type, report_focus, checklist_type, len(uploaded_files))
        
        final_report = call_openrouter(prompt, max_tokens=4000)
        
        # Add batch processing summary at top
        header = f"""{'='*70}
BATCH PROCESSING SUMMARY
{'='*70}
Total Files Processed: {len(uploaded_files)}
Number of Batches: {len(batch_reports)}
Files per Batch: {BATCH_SIZE}
Processing Method: Sequential batch analysis with AI synthesis

{'='*70}

"""
        
        return header + final_report
    
    except Exception as e:
        print(f"Synthesis error: {e}")
        # Fallback: concatenate batch reports
        combined = "# FINANCIAL DUE DILIGENCE REPORT\n\n"
        combined += "**Note:** Report generated from batch processing\n\n"
        for br in batch_reports:
            combined += f"\n## Batch {br['batch_number']} Analysis\n\n"
            combined += br['report'] + "\n\n"
        return combined


def call_openrouter(prompt, max_tokens=3000):
    """Make API call to OpenRouter"""
    free_models = [
        "meta-llama/llama-3.1-8b-instruct:free",
        "google/gemma-2-9b-it:free",
        "microsoft/phi-3-mini-128k-instruct:free",
    ]
    
    for model in free_models:
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
                        {"role": "system", "content": "You are an expert M&A financial analyst."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.5
                },
                timeout=45
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"  Model {model} failed: {str(e)[:50]}")
            continue
    
    return "Error: All models failed"


def create_batch_prompt(batch_docs, batch_num, total_batches, dd_type, report_focus):
    """Create prompt for analyzing a single batch"""
    files_list = "\n".join([f"- {doc['filename']}: {doc['summary'][:500]}..." for doc in batch_docs])
    
    return f"""You are analyzing BATCH {batch_num} of {total_batches} for a {dd_type} - {report_focus}.

FILES IN THIS BATCH:
{files_list}

Analyze these {len(batch_docs)} documents and provide:

1. **Key Financial Findings**
   - Revenue, profitability, margins (actual numbers)
   - Balance sheet highlights
   - Cash flow observations

2. **Notable Items**
   - Significant transactions
   - Contract terms
   - Compliance issues

3. **Risks Identified**
   - List 3-5 specific risks from these documents
   - Rate as High/Medium/Low

4. **Data Gaps**
   - What information is missing?

Keep response focused and data-driven. This is batch {batch_num} of {total_batches}.
"""


def create_synthesis_prompt(batch_reports_content, dd_type, report_focus, checklist_type, total_files):
    """Create prompt for synthesizing all batch reports"""
    return f"""You are synthesizing {total_files} documents analyzed in multiple batches into ONE comprehensive {dd_type} - {report_focus}.

BATCH ANALYSIS RESULTS:
{batch_reports_content}

Create a unified, professional due diligence report with:

## EXECUTIVE SUMMARY
- Overall assessment across all documents
- Key findings (5-7 points with numbers)
- Investment recommendation (Buy/Hold/Pass)
- Critical concerns

## CONSOLIDATED FINANCIAL ANALYSIS
- Revenue trends and growth rates
- Profitability metrics (margins, EBITDA)
- Balance sheet summary
- Cash flow assessment
- Working capital position

## COMPREHENSIVE RISK ASSESSMENT
- Top 10 risks across all documents
- Categorized by severity (High/Medium/Low)
- Impact analysis

## OPERATIONAL HIGHLIGHTS
- Business model observations
- Customer/supplier concentrations
- Contract terms and commitments

## VALUATION CONSIDERATIONS
- Key value drivers identified
- Quality of earnings adjustments
- Normalized EBITDA considerations

## FINAL RECOMMENDATION
- Go/No-go decision with detailed rationale
- Suggested price adjustments
- Required additional diligence
- Deal-breaker issues (if any)

Synthesize insights from ALL batches into ONE cohesive analysis. Focus on patterns, consistencies, and contradictions across documents.
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
            if len(text) > 25000:
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
