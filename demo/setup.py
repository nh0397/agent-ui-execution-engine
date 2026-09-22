"""Initialize ignored configuration, preserving existing nonempty settings."""
import secrets
from pathlib import Path

def main():
    path=Path('.env')
    text=path.read_text(encoding='utf-8') if path.exists() else ''
    defaults={'LLM_PROVIDER':'ollama','GROQ_API_KEY':'','GROQ_MODEL':'openai/gpt-oss-20b','OLLAMA_URL':'http://127.0.0.1:11434','LLM_DAILY_REQUEST_LIMIT':'100'}
    keys={line.partition('=')[0].strip():line.partition('=')[2].strip() for line in text.splitlines() if '=' in line and not line.lstrip().startswith('#')}
    if not keys.get('DEMO_DB_PASSWORD'):
        text='\n'.join(line for line in text.splitlines() if not line.startswith('DEMO_DB_PASSWORD='))
        text+='\nDEMO_DB_PASSWORD='+secrets.token_hex(24)+'\n'
    for key,value in defaults.items():
        if key not in keys:text+='\n'+key+'='+value
    path.write_text(text.rstrip()+'\n',encoding='utf-8')
    print('Local configuration prepared; existing credentials preserved.')

if __name__=='__main__':main()
