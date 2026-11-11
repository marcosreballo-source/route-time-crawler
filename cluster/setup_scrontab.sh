#!/bin/bash

# Find absolute path of the directory containing this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SBATCH_PATH="$SCRIPT_DIR/run_collector.sbatch"
LOGS_DIR="$( cd "$SCRIPT_DIR/.." && pwd )/logs"

# Verify file exists
if [ ! -f "$SBATCH_PATH" ]; then
    echo "Error: run_collector.sbatch not found at $SBATCH_PATH"
    exit 1
fi

echo "Installing scrontab scheduling..."
echo "Using batch script: $SBATCH_PATH"
echo "Writing logs to: $LOGS_DIR"

# Generate and load standard crontab
cat << EOF | crontab -
# Intensive 2-week scheduling for route-matrix collection
# Matches the approved R\$600 budget limit.

# Todos os dias: Morning Rush (07:00 - 09:30 a cada 30 min)
0,30 7-9 * * * cd $SCRIPT_DIR/.. && sbatch $SBATCH_PATH

# Todos os dias: Evening Peak (16:00 - 22:00 a cada 30 min)
0,30 16-22 * * * cd $SCRIPT_DIR/.. && sbatch $SBATCH_PATH

# Todos os dias: Esparso (12:00, 14:00, 23:00, 04:00)
0 4,12,14,23 * * * cd $SCRIPT_DIR/.. && sbatch $SBATCH_PATH
EOF

echo "crontab updated successfully. List configured schedules with: crontab -l"
