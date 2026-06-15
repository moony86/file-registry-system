#!/bin/bash
# start_all.sh - تشغيل كل السيرفرات في جهاز واحد

echo "🚀 Starting File Registry System..."
echo "=================================="

# التأكد من وجود البيئة الافتراضية
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# تثبيت المتطلبات
echo "📦 Installing dependencies..."
pip install -q -r master-node/requirements.txt
pip install -q -r storage-node/requirements.txt
pip install -q rich click requests

# تشغيل Master Node
echo "🟢 Starting Master Node on port 5000..."
cd master-node
python app.py &
MASTER_PID=$!
cd ..

sleep 3

# تشغيل Storage Node A
echo "💾 Starting Storage Node A on port 5001..."
NODE_ID="node-a" NODE_HOST="localhost" NODE_PORT="5001" MASTER_URL="http://localhost:5000" \
    python storage-node/app.py &
NODE_A_PID=$!

# تشغيل Storage Node B
echo "💾 Starting Storage Node B on port 5002..."
NODE_ID="node-b" NODE_HOST="localhost" NODE_PORT="5002" MASTER_URL="http://localhost:5000" \
    python storage-node/app.py &
NODE_B_PID=$!

# تشغيل Storage Node C
echo "💾 Starting Storage Node C on port 5003..."
NODE_ID="node-c" NODE_HOST="localhost" NODE_PORT="5003" MASTER_URL="http://localhost:5000" \
    python storage-node/app.py &
NODE_C_PID=$!

echo ""
echo "✅ All services started!"
echo "========================="
echo "Master:    http://localhost:5000"
echo "Node A:    http://localhost:5001"
echo "Node B:    http://localhost:5002"
echo "Node C:    http://localhost:5003"
echo ""
echo "PIDs: Master=$MASTER_PID, A=$NODE_A_PID, B=$NODE_B_PID, C=$NODE_C_PID"
echo ""
echo "Press Ctrl+C to stop all services"

# انتظار Ctrl+C
trap "kill $MASTER_PID $NODE_A_PID $NODE_B_PID $NODE_C_PID 2>/dev/null; echo '👋 Shutting down...'" INT
wait
