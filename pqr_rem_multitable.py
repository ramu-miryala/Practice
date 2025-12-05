import os
import psycopg2
from groq import Groq
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import json

# PostgreSQL Connection 
POSTGRES_HOST = "192.168.0.13"
POSTGRES_PORT = "5432"
POSTGRES_DATABASE = "itciot" 
POSTGRES_USER = "itc"  
POSTGRES_PASSWORD = "ITCadmin@13" 




conversation_history = []

def get_db_connection():
    """Connect to PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DATABASE,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None


def get_database_schema():
    """Fetch database schema with relationships to provide context to LLM"""
    conn = get_db_connection()
    if not conn:
        return "Unable to fetch schema - check your database connection"
    
    try:
        cursor = conn.cursor()
        
        # Get all tables in schema 'itciot'
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'itciot'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        if not tables:
            cursor.close()
            conn.close()
            return "No tables found in the database"
        
        schema_info = "Database Schema with Relationships:\n\n"
        
        for table in tables:
            table_name = table[0]
            full_table_name = f"itciot.{table_name}"  # fully qualified name
            
            # Get columns
            cursor.execute(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_schema = 'itciot' AND table_name = '{table_name}'
                ORDER BY ordinal_position
            """)
            columns = cursor.fetchall()
            
            schema_info += f"Table: {full_table_name}\n"
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                schema_info += f"  - {col[0]} ({col[1]}) {nullable}\n"
            
            # Get foreign keys
            cursor.execute(f"""
                SELECT
                    kcu.column_name,
                    ccu.table_schema AS foreign_table_schema,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'itciot'
                  AND tc.table_name = '{table_name}'
            """)
            foreign_keys = cursor.fetchall()
            
            if foreign_keys:
                schema_info += f"  Foreign Keys:\n"
                for fk in foreign_keys:
                    fk_full_table = f"{fk[1]}.{fk[2]}"  # schema + table
                    schema_info += f"    - {fk[0]} -> {fk_full_table}.{fk[3]}\n"
            
            schema_info += "\n"
        
        # Common JOIN hints
        schema_info += """
Common JOIN Patterns:
- join itciot.users
- To get employee with benefits: JOIN itciot.employee_data with itciot.benefits
- To get employee with pension: JOIN itciot.employee_data with itciot.pension_details
- To get employee with retirement: JOIN itciot.employee_data with itciot.retirement
- Use appropriate JOIN keys (usually emp_id or employee_id)
"""
        print(schema_info)
        cursor.close()
        conn.close()

        return schema_info

    except Exception as e:
        print(f"Error fetching schema: {e}")
        return f"Error fetching schema: {e}"


def natural_language_to_sql(question, schema, context=""):
    """Convert natural language question to SQL using Groq with multi-table support"""
    print("=== Starting SQL generation ===")
    print("Question:", question)
    
    try:
        client = Groq(api_key=GROQ_API_KEY)
        print("Groq client initialized:", client)
        
        # Show the schema size
        print("\n=== Schema ===")
        print(schema)
        print("Schema length (characters):", len(schema))
        
        # Show the context if any
        if context:
            print("\n=== Context ===")
            print(context)
            print("Context length (characters):", len(context))
        else:
            print("\nNo previous context provided.")
        
        # Build the prompt
        prompt = f"""
You are an expert SQL query generator. Generate a PostgreSQL SELECT query.

Schema:
{schema}

Context: {context}

Question: {question}

Generate only the SQL query without explanations or semicolons.
"""
        print("\n=== Final prompt to be sent to Groq ===")
        print(prompt)
        print("Prompt length (characters):", len(prompt))
        
        # Send request to Groq
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
        )

        print("\n=== Raw Groq response ===")
        print(chat_completion)
        
        sql_query = chat_completion.choices[0].message.content.strip()
        print("\n=== Extracted SQL query ===")
        print(sql_query)
        
        return sql_query

    except Exception as e:
        print(f"Error generating SQL: {e}")
        return None


def execute_sql_query(sql_query):
    """Execute SQL query and return results"""
    conn = get_db_connection()
    if not conn:
        return {"error": "Could not connect to database"}
    
    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        
        # Fetch results
        results = cursor.fetchall()
        
        # Get column names
        column_names = [desc[0] for desc in cursor.description]
        
        cursor.close()
        conn.close()
        
        return {"columns": column_names, "rows": results}
        
    except Exception as e:
        print(f"Error executing query: {e}")
        return {"error": str(e)}

# FLASK WEB APP

app = Flask(__name__)
CORS(app)

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chatbot</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 10px;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 1400px;
            height: 95vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 28px;
            margin-bottom: 5px;
        }
        
        .header p {
            opacity: 0.9;
            font-size: 14px;
        }
        
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
            background: #f8f9fa;
        }
        
        .message {
            margin-bottom: 20px;
            display: flex;
            gap: 15px;
        }
        
        .message.user {
            justify-content: flex-end;
        }
        
        .message-content {
            max-width: 80%;
            padding: 15px 20px;
            border-radius: 15px;
            line-height: 1.5;
        }
        
        .message.user .message-content {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-bottom-right-radius: 5px;
        }
        
        .message.bot .message-content {
            background: white;
            color: #333;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border-bottom-left-radius: 5px;
        }
        
        .results-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 14px;
            overflow-x: auto;
            display: block;
        }
        
        .results-table th {
            background: #667eea;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
        }
        
        .results-table td {
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
        }
        
        .results-table tr:hover {
            background: #f7fafc;
        }
        
        .input-container {
            padding: 20px 30px;
            background: white;
            border-top: 1px solid #e2e8f0;
            display: flex;
            gap: 15px;
        }
        
        #questionInput {
            flex: 1;
            padding: 15px 20px;
            border: 2px solid #e2e8f0;
            border-radius: 25px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.3s;
        }
        
        #questionInput:focus {
            border-color: #667eea;
        }
        
        #sendBtn {
            padding: 15px 35px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        #sendBtn:hover {
            transform: translateY(-2px);
        }
        
        #sendBtn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        #clearBtn {
            padding: 15px 25px;
            background: #e53e3e;
            color: white;
            border: none;
            border-radius: 25px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        #clearBtn:hover {
            transform: translateY(-2px);
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error {
            color: #e53e3e;
            font-weight: 600;
        }
        
        .results-header {
            font-weight: 600;
            color: #667eea;
            margin-bottom: 10px;
            font-size: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        
        .action-btn {
            padding: 8px 15px;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .action-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        
        .btn-copy {
            background: white;
            color: black;
        }
        
        .btn-excel {
            background: white;
            color: black;
        }
        
        .btn-image {
            background: white;
            color: black;
        }
        
        .result-wrapper {
            position: relative;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>ChatBot</h1>
        </div>
        
        <div class="chat-container" id="chatContainer">
            <div class="message bot">
                <div class="message-content">
                    Hello! I can query data across tables. Ask me anything!
                </div>
            </div>
        </div>
        
        <div class="input-container">
            <input type="text" id="questionInput" placeholder="Ask Here" />
            <button id="sendBtn" onclick="sendQuestion()">Send</button>
            <button id="clearBtn" onclick="clearHistory()">Clear Chat</button>
        </div>
    </div>

    <script>
        const chatContainer = document.getElementById('chatContainer');
        const questionInput = document.getElementById('questionInput');
        const sendBtn = document.getElementById('sendBtn');
        
        questionInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendQuestion();
            }
        });
        
        function addMessage(content, isUser = false) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${isUser ? 'user' : 'bot'}`;
            
            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            contentDiv.innerHTML = content;
            
            messageDiv.appendChild(contentDiv);
            chatContainer.appendChild(messageDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        function copyTableToClipboard(tableId) {
            const table = document.getElementById(tableId);
            const range = document.createRange();
            range.selectNode(table);
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
            
            try {
                document.execCommand('copy');
                alert('Table copied to clipboard!');
            } catch (err) {
                alert('Failed to copy table');
            }
            
            window.getSelection().removeAllRanges();
        }
        
        function downloadAsExcel(tableId, filename = 'results.xlsx') {
            const table = document.getElementById(tableId);
            const wb = XLSX.utils.table_to_book(table, {sheet: "Results"});
            XLSX.writeFile(wb, filename);
        }
        
        function saveAsImage(tableId, filename = 'results.jpg') {
            const table = document.getElementById(tableId);
            
            html2canvas(table, {
                scale: 2,
                backgroundColor: '#ffffff',
                logging: false
            }).then(canvas => {
                canvas.toBlob(function(blob) {
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement('a');
                    link.download = filename;
                    link.href = url;
                    link.click();
                    URL.revokeObjectURL(url);
                }, 'image/jpeg', 0.95);
            });
        }
        
        let resultCounter = 0;
        
        async function sendQuestion() {
            const question = questionInput.value.trim();
            if (!question) return;
            
            addMessage(question, true);
            questionInput.value = '';
            sendBtn.disabled = true;
            
            addMessage('<div class="loading"></div>');
            
            try {
                const response = await fetch('/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question })
                });
                
                const data = await response.json();
                
                // Remove loading message
                chatContainer.lastChild.remove();
                
                if (data.error) {
                    addMessage(`<span class="error">Error: ${data.error}</span>`);
                } else {
                    let responseHTML = '';
                    
                    if (data.results && data.results.rows && data.results.rows.length > 0) {
                        resultCounter++;
                        const tableId = `result-table-${resultCounter}`;
                        const timestamp = new Date().toISOString().slice(0,19).replace(/:/g,'-');
                        
                        responseHTML += `
                            <div class="result-wrapper">
                                <div class="results-header">
                                    <span>Results (${data.results.rows.length} rows):</span>
                                    <div class="action-buttons">
                                        <button class="action-btn btn-copy" onclick="copyTableToClipboard('${tableId}')" title="Copy to clipboard">
                                            Copy
                                        </button>
                                        <button class="action-btn btn-excel" onclick="downloadAsExcel('${tableId}', 'results_${timestamp}.xlsx')" title="Download as Excel">
                                            Excel
                                        </button>
                                        <button class="action-btn btn-image" onclick="saveAsImage('${tableId}', 'results_${timestamp}.jpg')" title="Save as Image">
                                            Image
                                        </button>
                                    </div>
                                </div>
                                <table class="results-table" id="${tableId}"><thead><tr>`;
                        
                        data.results.columns.forEach(col => {
                            responseHTML += `<th>${col}</th>`;
                        });
                        
                        responseHTML += '</tr></thead><tbody>';
                        
                        data.results.rows.forEach(row => {
                            responseHTML += '<tr>';
                            row.forEach(cell => {
                                responseHTML += `<td>${cell !== null ? cell : 'NULL'}</td>`;
                            });
                            responseHTML += '</tr>';
                        });
                        
                        responseHTML += '</tbody></table></div>';
                    } else {
                        responseHTML += '<p>No results found.</p>';
                    }
                    
                    addMessage(responseHTML);
                }
            } catch (error) {
                chatContainer.lastChild.remove();
                addMessage(`<span class="error">Error: ${error.message}</span>`);
            }
            
            sendBtn.disabled = false;
        }
        
        async function clearHistory() {
            if (confirm('Clear chat history? This will reset the conversation context.')) {
                try {
                    await fetch('/clear-history', { method: 'POST' });
                    chatContainer.innerHTML = `
                        <div class="message bot">
                            <div class="message-content">
                                Chat history cleared! Ask me anything.
                            </div>
                        </div>
                    `;
                    resultCounter = 0;
                } catch (error) {
                    alert('Error clearing history: ' + error.message);
                }
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/query', methods=['POST'])
def query():
    global conversation_history
    
    try:
        data = request.json
        question = data.get('question', '')
        
        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        # Get schema with relationships
        schema = get_database_schema()
        
        if "Unable to fetch schema" in schema or "No tables found" in schema:
            return jsonify({'error': schema}), 500
        
        # Build context from conversation history
        context = ""
        if conversation_history:
            context = "\n\n Previous conversation context:\n"
            for i, item in enumerate(conversation_history[-3:]):  # Last 3 exchanges
                context += f"Q{i+1}: {item['question']}\n"
                context += f"SQL{i+1}: {item['sql']}\n"
        
        # Generate SQL with context
        sql_query = natural_language_to_sql(question, schema, context)
        
        if not sql_query:
            return jsonify({'error': 'Could not generate SQL query'}), 500
        
        # Print SQL to terminal only
        print("\n" + "="*60)
        print("GENERATED SQL QUERY:")
        print("="*60)
        print(sql_query)
        print("="*60 + "\n")
        
        # Execute SQL
        results = execute_sql_query(sql_query)
        
        if results and 'error' in results:
            return jsonify({'error': results['error'], 'sql': sql_query}), 500
        
        # Store in conversation history
        conversation_history.append({
            'question': question,
            'sql': sql_query,
            'results': results
        })
        
        # Keep only last 10 conversations
        if len(conversation_history) > 10:
            conversation_history = conversation_history[-10:]
        
        # Return results without SQL query (SQL won't be shown in UI)
        return jsonify({
            'results': results
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/clear-history', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = []
    return jsonify({'success': True})

# START SERVER
if __name__ == "__main__":
    print("=" * 60)
    print(" Starting Chatbot")
    print("=" * 60)
    
    # Test database connection
    print("\n Testing PostgreSQL connection...")
    conn = get_db_connection()
    if conn:
        print("Database connection successful!")
        
        # Show available tables and relationships
        schema = get_database_schema()
        print("\n" + schema)
        
        conn.close()
    else:
        print("Failed to connect to PostgreSQL!")
        print(f"   Host: {POSTGRES_HOST}")
        print(f"   Port: {POSTGRES_PORT}")
        print(f"   Database: {POSTGRES_DATABASE}")
        print(f"   User: {POSTGRES_USER}")
    
    print("=" * 60)
    print("Open: http://localhost:5000")
    print("Now supports multi-table queries with JOINs!")
    print("SQL queries will be shown only in terminal")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print("\n")
    
    app.run(host='0.0.0.0', port=5000, debug=True)