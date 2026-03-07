import asyncio
import websockets
#import aioconsole # Optional: pip install aioconsole for better async input

async def chat():
    uri = "ws://localhost:8000/ws/123" # 123 is a dummy client_id
    
    async with websockets.connect(uri) as websocket:
        print("--- Connected to Chat Server ---")
        
        # Task to handle receiving messages
        async def receive_messages():
            try:
                while True:
                    message = await websocket.recv()
                    print(f"\n[New Message] {message}")
            except websockets.ConnectionClosed:
                print("Connection to server closed.")

        # Task to handle sending messages
        async def send_messages():
            while True:
                # Use aioconsole for non-blocking input, or standard input
                msg = await asyncio.to_thread(input, "You: ")
                if msg.lower() == 'exit':
                    break
                await websocket.send(msg)

        # Run both tasks concurrently
        await asyncio.gather(receive_messages(), send_messages())

if __name__ == "__main__":
    asyncio.run(chat())