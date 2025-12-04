import asyncio
import chromadb
import os
import json
import hashlib
import yaml

# Configuration
exp_db_config_path = 'configs/exp_db_config.yaml'
exp_db_config = None

# --- Sample Data WITHOUT IDs ---
# Note: We removed the "id" field to simulate raw incoming text
DATASET = [
    {
        "name": "Alice Smith",
        "role": "Senior Engineer",
        "department": "Engineering",
        "skills": ["Python", "Docker", "FastAPI"],
        "active": True
    },
    {
        "name": "Bob Jones",
        "role": "Product Manager",
        "department": "Product",
        "skills": ["Agile", "User Research"],
        "active": True
    },
    {
        "name": "Charlie Davis",
        "role": "Junior Engineer",
        "department": "Engineering",
        "skills": ["Python", "React"],
        "active": False
    }
]

async def main():
    

    try:
        try:
            with open(exp_db_config_path, 'r') as file:
                global exp_db_config
                exp_db_config = yaml.safe_load(file)
        except FileNotFoundError:
            print(f"Error: The file '{exp_db_config_path}' was not found.")
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file: {e}")
        
        print(f"--- Testing Connection to {exp_db_config['hostname']}:{exp_db_config['port']} ---")
        client = await chromadb.AsyncHttpClient(host=exp_db_config['hostname'], port=exp_db_config['port'])
        
        
        
        # Reset collection for clean test
        try: await client.delete_collection(exp_db_config['collection_name'])
        except: pass 
        
        collection = await client.get_or_create_collection(name=exp_db_config['collection_name'])
        print(f"✅ Collection '{exp_db_config['collection_name']}' ready.")

        # --- Processing Data ---
        print("➡️  Generating Auto-IDs and processing data...")
        
        ids = []
        documents = []
        metadatas = []

        for item in DATASET:
            # OPTION 1: Random UUID (Best for general auto-increment behavior)
            # This generates a unique string like 'a1b2c3d4-...'
            #auto_id = str(uuid.uuid4())
            
            # OPTION 2: Content-Based Hash (Advanced)
            # Use this if you want to prevent duplicates. If the content is the same, the ID is the same.
            
            content_str = json.dumps(item, sort_keys=True)
            auto_id = hashlib.md5(content_str.encode()).hexdigest()

            ids.append(auto_id)
            
            # Prepare document and metadata
            documents.append(json.dumps(item))
            metadatas.append({
                "role": item["role"],
                "department": item["department"],
                "active": item["active"]
            })
            
            print(f"   Generated ID: {auto_id} -> {item['name']}")

        # Add to Chroma
        await collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        print(f"✅ Added {len(ids)} items with auto-generated IDs.")

        # Query to verify
        results = await collection.query(
            query_texts=["Engineer"],
            n_results=1
        )
        
        print("\n--- Verification Query ---")
        print(f"Retrieved ID: {results['ids'][0][0]}")
        print(f"Document: {results['documents'][0][0]}")
        print(f"Metadata: {results['metadatas'][0][0]}")
        print(await client.list_collections())
        await client.close()
        

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())