import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime
import re

csv_path = "Consumed_API_-_Request_count_(filtered)_[SUM].csv"

# Ler o arquivo ignorando o cabeçalho complexo e pegando as linhas com dados
data = []
with open(csv_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line or "TimeSeries" in line or "project_id" in line:
            continue
        
        # Ex: "Mon Jun 22 2026 01:05:00 GMT-0300 (Horário Padrão de Brasília),1"
        # Separar pela vírgula
        parts = line.split(',')
        if len(parts) != 2:
            continue
            
        date_str_full = parts[0]
        try:
            count = float(parts[1])
        except ValueError:
            continue
        
        # Extrair só a parte da data e hora: "Mon Jun 22 2026 01:05:00"
        match = re.search(r"^[A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{4} \d{2}:\d{2}:\d{2}", date_str_full)
        if match:
            date_str = match.group(0)
            dt = datetime.strptime(date_str, "%a %b %d %Y %H:%M:%S")
            data.append({"datetime": dt, "count": count})

df = pd.DataFrame(data)

# Extrair data e hora do dia (como um float para o eixo Y, de 0 a 24)
df['date'] = df['datetime'].dt.date
df['time_of_day'] = df['datetime'].dt.hour + df['datetime'].dt.minute / 60.0

# Configurar o estilo
plt.style.use('dark_background')
sns.set_theme(style="darkgrid", rc={"axes.facecolor": "#121212", "figure.facecolor": "#121212"})
fig, ax = plt.subplots(figsize=(12, 7))

# Plotar os pontos
sns.scatterplot(
    data=df, 
    x='date', 
    y='time_of_day', 
    s=150, 
    color="#00E676", 
    edgecolor="white", 
    alpha=0.9, 
    ax=ax,
    zorder=3
)

# Destacar as zonas alvo (Morning Rush e Evening Rush)
ax.axhspan(7, 9.5, color='#4FC3F7', alpha=0.2, zorder=1, label="Alvo: Pico da Manhã (07h-09h)")
ax.axhspan(16, 22.5, color='#FF8A65', alpha=0.2, zorder=1, label="Alvo: Pico da Noite (16h-22h)")

# Formatar os eixos
ax.set_ylim(0, 24)
ax.set_yticks(range(0, 25, 2))
ax.set_yticklabels([f"{h:02d}:00" for h in range(0, 25, 2)], color="white")

# Formatar o eixo X
ax.set_xticks(df['date'].unique())
ax.set_xticklabels([d.strftime('%d %b') for d in df['date'].unique()], color="white", fontsize=11)

plt.title("Coleta Automatizada de Dados de Tráfego - Linha do Tempo de Execução (UTC-3)", color="white", fontsize=16, pad=20)
plt.ylabel("Hora do Dia (BRT)", color="white", fontsize=12, labelpad=10)
plt.xlabel("Data (2026)", color="white", fontsize=12, labelpad=10)

# Customizar a legenda
legend = ax.legend(loc='lower left', facecolor='#1e1e1e', edgecolor='gray', labelcolor='white')

# Adicionar textos explicativos
# plt.text(df['date'].unique()[1], 14.5, "Deslocamento UTC\n(Horário Incorreto)", color="#FF5252", 
#         ha='center', va='center', fontsize=10, bbox=dict(facecolor='#121212', edgecolor='none', alpha=0.7))

#plt.text(df['date'].unique()[-1], 21, "Horário Corrigido\n(Alinhado aos Alvos)", color="#00E676", 
#         ha='center', va='center', fontsize=10, bbox=dict(facecolor='#121212', edgecolor='none', alpha=0.7))

plt.tight_layout()
plt.savefig("bot_execution_timeline.png", dpi=300, bbox_inches='tight', facecolor=fig.get_facecolor())
print("Gráfico gerado com sucesso em: bot_execution_timeline.png")
