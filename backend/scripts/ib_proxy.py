"""
IB Gateway TCP Proxy for debugging ngrok tunnel issues.
This proxy sits between our app and the ngrok tunnel to log handshake traffic.
"""
import asyncio
import logging
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("ib_proxy")

IB_NGROK_HOST = os.environ.get("IB_HOST", "5.tcp.ngrok.io")
IB_NGROK_PORT = int(os.environ.get("IB_PORT", 29573))
LOCAL_PROXY_PORT = 4003  # Our proxy listens here

async def pipe(reader, writer, direction):
    """Pipe data between connections and log it"""
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
            logger.info(f"{direction}: {len(data)} bytes")
            logger.debug(f"{direction} data: {data[:200]}")  # First 200 bytes
            writer.write(data)
            await writer.drain()
    except Exception as e:
        logger.error(f"{direction} error: {e}")
    finally:
        writer.close()

async def handle_client(local_reader, local_writer):
    """Handle incoming connection from ib_insync"""
    client_addr = local_writer.get_extra_info('peername')
    logger.info(f"New connection from {client_addr}")
    
    try:
        # Connect to ngrok tunnel
        logger.info(f"Connecting to ngrok tunnel at {IB_NGROK_HOST}:{IB_NGROK_PORT}")
        remote_reader, remote_writer = await asyncio.wait_for(
            asyncio.open_connection(IB_NGROK_HOST, IB_NGROK_PORT),
            timeout=10
        )
        logger.info("Connected to ngrok tunnel!")
        
        # Pipe data both ways
        await asyncio.gather(
            pipe(local_reader, remote_writer, "CLIENT->IB"),
            pipe(remote_reader, local_writer, "IB->CLIENT")
        )
    except asyncio.TimeoutError:
        logger.error("Timeout connecting to ngrok tunnel")
    except Exception as e:
        logger.error(f"Connection error: {e}")
    finally:
        local_writer.close()
        logger.info(f"Connection from {client_addr} closed")

async def main():
    server = await asyncio.start_server(
        handle_client, '127.0.0.1', LOCAL_PROXY_PORT
    )
    
    addr = server.sockets[0].getsockname()
    logger.info(f"IB Proxy listening on {addr}")
    logger.info(f"Forwarding to {IB_NGROK_HOST}:{IB_NGROK_PORT}")
    logger.info(f"Configure your app to connect to 127.0.0.1:{LOCAL_PROXY_PORT}")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
