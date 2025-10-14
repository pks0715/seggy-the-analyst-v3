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

# Initialize API clients
print("Initializing API clients...")

# Cohere (Primary for summarization)
cohere_client = None
try:
    cohere_client = cohere.ClientV2(api_key=os.environ.get('COHERE_API_KEY'))
    print("✓ Cohere initialized")
except Exception as e:
    print(f"✗ Cohere failed: {e}")

# OpenRouter (Primary for report generation)
openrouter_key = os.environ.get('OPENROUTER_API_KEY')
if openrouter_key:
    print("✓ OpenRouter key available")
else:
    print("✗ OpenRouter key missing")

# HuggingFace (For metric extraction)
huggingface_key = os.environ.get('HUGGINGFACE_API_KEY')
if huggingface_key:
    print("✓ HuggingFace key available")
else:
    print("✗ HuggingFace key missing")

print("API initialization complete\n")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        start_time = time.time()
        
        dd_type = request.form.get('dd_type', 'M&A Due Diligence')
        report_focus = request.form.get('report_focus', 'Financial Report')
        checklist_type = request.form.get('checklist_type', 'Simple')
        
        files = request.files.getlist('files')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files uploaded'}), 400
        
        # Extract text from all files
        all_documents = []
        uploaded_files = []
        
        print(f"Processing {len(files)} files...")
        
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
                            'content': extracted_content
                        })
            else:
                filename = file.filename
                uploaded_files.append(filename)
                
                pdf_text = extract_pdf_text(file)
                if pdf_text:
                    all_documents.append({
                        'filename': filename,
                        'content': pdf_text
                    })
        
        if not all_documents:
            return jsonify({'error': 'Could not extract text from any files'}), 400
        
        print(f"Extracted text from {len(all_documents)} documents")
        
        # STEP 1: Summarize with Cohere
        print("Step 1: Summarizing documents with Cohere...")
        summarized_docs = summarize_documents_cohere(all_documents)
        
        # STEP 2: Extract financial metrics with HuggingFace
        print("Step 2: Extracting financial metrics with HuggingFace...")
        financial_metrics = extract_financial_metrics_hf(all_documents[:3])
        
        # STEP 3: Generate report
        print("Step 3: Generating report with OpenRouter...")
        report = generate_report_openrouter(
            summarized_docs,
            financial_metrics,
            dd_type,
            report_focus,
            checklist_type,
            uploaded_files
        )
        
        if time.time() - start_time > 100:
            print("Warning: Processing taking longer than expected")
        
        # STEP 4: Generate charts
        print("Step 4: Generating charts and visualizations...")
        extracted_data = extract_financial_data_from_report(report)
        charts_html = generate_visual_report(report, extracted_data)
        
        print(f"✓ Complete! Total time: {time.time() - start_time:.2f}s")
        
        return jsonify({
            'report': report,
            'charts': charts_html,
            'uploaded_files': uploaded_files,
            'total_files': len(uploaded_files)
        })
    
    except Exception as e:
        print(f"Error in analyze: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

def extract_zip_file(zip_file):
    """Extract PDF files from ZIP archive"""
    extracted_files = []
    
    try:
        zip_bytes = zip_file.read()
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zip_ref:
            for file_info in zip_ref.filelist:
                if file_info.is_dir():
                    continue
                
                filename = file_info.filename
                
                if filename.lower().endswith('.pdf'):
                    try:
                        pdf_bytes = zip_ref.read(file_info)
                        pdf_text = extract_pdf_from_bytes(pdf_bytes)
                        
                        clean_filename = os.path.basename(filename)
                        extracted_files.append((clean_filename, pdf_text))
                    except Exception as e:
                        print(f"Error extracting {filename} from ZIP: {e}")
                        continue
        
        return extracted_files
    except Exception as e:
        print(f"Error processing ZIP file: {e}")
        return []

def extract_pdf_from_bytes(pdf_bytes):
    """Extract text from PDF bytes"""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        text = ""
        
        page_count = min(50, len(pdf_reader.pages))
        
        for page_num in range(page_count):
            page = pdf_reader.pages[page_num]
            text += page.extract_text() + "\n"
        
        return text.strip()
    except Exception as e:
        print(f"Error extracting PDF from bytes: {e}")
        return None

def extract_pdf_text(file):
    """Extract text from PDF file"""
    try:
        file_bytes = file.read()
        return extract_pdf_from_bytes(file_bytes)
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return None

def summarize_documents_cohere(documents):
    """Use Cohere to summarize documents before analysis"""
    summarized = []
    
    if not cohere_client:
        print("Cohere not available, using truncated originals")
        return [{'filename': d['filename'], 'summary': d['content'][:3000], 'full_content': d['content'][:10000]} for d in documents[:5]]
    
    try:
        for doc in documents[:5]:
            text = doc['content'][:4000]
            
            try:
                response = cohere_client.summarize(
                    text=text,
                    length='long',
                    format='bullets',
                    model='command',
                    additional_command='Focus on financial metrics, revenue, expenses, assets, liabilities, and key business insights.'
                )
                
                summarized.append({
                    'filename': doc['filename'],
                    'summary': response.summary,
                    'full_content': doc['content'][:10000]
                })
                print(f"  ✓ Summarized {doc['filename']}")
            except Exception as e:
                print(f"  ✗ Cohere failed for {doc['filename']}: {e}")
                summarized.append({
                    'filename': doc['filename'],
                    'summary': text[:2000],
                    'full_content': doc['content'][:10000]
                })
        
        return summarized
    except Exception as e:
        print(f"Cohere API error: {e}")
        return [{'filename': d['filename'], 'summary': d['content'][:2000], 'full_content': d['content'][:10000]} for d in documents[:5]]

def extract_financial_metrics_hf(documents):
    """Use HuggingFace to extract specific financial metrics"""
    metrics = {}
    
    if not huggingface_key:
        print("HuggingFace not available, skipping metric extraction")
        return metrics
    
    try:
        API_URL = "https://api-inference.huggingface.co/models/ProsusAI/finbert"
        headers = {"Authorization": f"Bearer {huggingface_key}"}
        
        for doc in documents:
            text = doc['content'][:500]
            
            try:
                response = requests.post(
                    API_URL, 
                    headers=headers, 
                    json={"inputs": text}, 
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    metrics[doc['filename']] = result
                    print(f"  ✓ Extracted metrics from {doc['filename']}")
            except Exception as e:
                print(f"  ✗ HF extraction failed for {doc['filename']}: {e}")
                continue
        
        return metrics
    except Exception as e:
        print(f"HuggingFace API error: {e}")
        return {}

def generate_report_openrouter(documents, metrics, dd_type, report_focus, checklist_type, uploaded_files):
    """Generate report using OpenRouter"""
    
    # Prepare content
    combined_text = "\n\n".join([
        f"DOCUMENT: {doc['filename']}\nSUMMARY: {doc['summary']}\n\nKEY CONTENT:\n{doc['full_content'][:5000]}"
        for doc in documents[:5]
    ])
    
    # Add extracted metrics
    if metrics:
        combined_text += f"\n\nEXTRACTED FINANCIAL METRICS:\n{str(metrics)[:1000]}"
    
    # Limit total size
    if len(combined_text) > 25000:
        combined_text = combined_text[:25000] + "\n\n[Content truncated...]"
    
    prompt = create_analysis_prompt(combined_text, dd_type, report_focus, checklist_type, uploaded_files)
    
    # Try OpenRouter models in order
    free_models = [
        "meta-llama/llama-3.1-70b-instruct",
        "google/gemini-pro-1.5",
        "meta-llama/llama-3.1-8b-instruct:free",
        "google/gemma-2-9b-it:free",
        "microsoft/phi-3-mini-128k-instruct:free"
    ]
    
    for model in free_models:
        try:
            print(f"  Trying OpenRouter model: {model}")
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "HTTP-Referer": "https://seggy-analyst.com",
                    "X-Title": "Seggy Due Diligence"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are an expert M&A financial analyst with 20+ years of experience."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 5000,
                    "temperature": 0.5
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                print(f"  ✓ Success with {model}")
                return f"[Generated using OPENROUTER: {model}]\n\n{content}"
            else:
                print(f"  ✗ {model} returned {response.status_code}")
        except Exception as e:
            print(f"  ✗ {model} failed: {e}")
            continue
    
    return "Error: All AI models failed to generate report. Please check your OpenRouter API key and try with fewer documents."

def create_analysis_prompt(content, dd_type, report_focus, checklist_type, uploaded_files):
    """Create standardized prompt for analysis"""
    return f"""You are a senior M&A financial analyst with 20+ years of experience. Generate a comprehensive due diligence report.

DOCUMENTS PROVIDED: {len(uploaded_files)} files
TYPE: {dd_type} - {report_focus}
CHECKLIST: {checklist_type}

CONTENT:
{content}

Generate a detailed, structured report with these sections:

# FINANCIAL DUE DILIGENCE REPORT

## EXECUTIVE SUMMARY
- Key Findings (3-5 points with actual numbers from documents)
- Investment Recommendation (Buy/Hold/Pass with rationale)
- Critical Issues requiring attention

## FINANCIAL ANALYSIS
- Revenue trends (extract actual figures and calculate growth rates)
- Profitability metrics (calculate actual margins from data)
- EBITDA reconciliation (build bridge from Net Income)
- Working capital analysis

## BALANCE SHEET REVIEW
- Assets breakdown (current and fixed)
- Liabilities analysis (short-term and long-term)
- Equity position
- Working capital calculation

## CASH FLOW ANALYSIS
- Operating cash flow trends
- Free cash flow calculation
- Cash conversion quality

## RISK ASSESSMENT
- Top 5-10 risks with severity ratings (High/Medium/Low)
- Red flags identified in documents
- Mitigation recommendations

## VALUATION CONSIDERATIONS
- Normalized EBITDA calculation
- Key value drivers
- Recommended adjustments
- Comparable multiples (if data available)

## CONCLUSIONS & RECOMMENDATIONS
- Overall assessment (detailed paragraph)
- Go/no-go recommendation with reasoning
- Price guidance implications
- Next steps for further diligence

CRITICAL INSTRUCTIONS:
1. Use ACTUAL DATA from the documents provided - extract specific numbers, percentages, dates
2. If data is missing, explicitly state "Not disclosed in provided documents"
3. Calculate ratios and metrics where possible
4. Be specific about which document each finding comes from
5. Maintain professional, objective tone throughout
6. Flag any data gaps or inconsistencies
7. Provide actionable insights, not just data regurgitation
8. Make this report immediately useful for investment decision-making

Generate the complete, professional report now.
"""

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
