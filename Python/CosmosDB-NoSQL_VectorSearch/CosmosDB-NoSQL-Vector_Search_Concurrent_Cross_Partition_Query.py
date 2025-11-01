import os
import uuid
import asyncio
import random
import json
import time
import logging
from functools import partial
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from dotenv import dotenv_values

# ------------------------
# CONFIGURATION
# ------------------------

# Load configuration from .env file
env_name = "sample_env_file.env"
config = dotenv_values(env_name)

COSMOS_DB_URI = config['cosmos_uri']
DATABASE_NAME = "vector-db"
CONTAINER_NAME = "vector-container"
AZURE_OPENAI_ENDPOINT = config['openai_endpoint']
AZURE_OPENAI_API_KEY = config['openai_key']
AZURE_OPENAI_API_VERSION = "2024-02-15-preview"
EMBEDDING_MODEL = config['openai_embeddings_deployment']
VECTOR_DIMENSIONS = 1536
NUM_RECORDS = 10000
OPENAI_CONCURRENCY = 3
MAX_RETRIES = 5
MAX_INGEST_CONCURRENCY = 5

# Initialize AzureOpenAI client
openai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_OPENAI_API_VERSION
)

# ------------------------
# COSMOS DB CONTAINER SETUP
# ------------------------
def create_cosmos_container():
    credential = DefaultAzureCredential()
    client = CosmosClient(COSMOS_DB_URI, credential)
    db = client.create_database_if_not_exists(id=DATABASE_NAME)

    vector_embedding_policy = {
        "vectorEmbeddings": [
            {
                "path": "/embedding",
                "dataType": "float32",
                "distanceFunction": "cosine",
                "dimensions": VECTOR_DIMENSIONS
            }
        ]
    }

    indexing_policy = {
        "includedPaths": [
            {"path": "/*"}
        ],
        "excludedPaths": [
            {"path": "/\"_etag\"/?"},
            {"path": "/embedding/*"}
        ],
        "vectorIndexes": [
            {
                "path": "/embedding",
                "type": "diskANN"
            }
        ]
    }

    try:
        container = db.create_container(
            id=CONTAINER_NAME,
            partition_key=PartitionKey(path="/id"),
            indexing_policy=indexing_policy,
            vector_embedding_policy=vector_embedding_policy,
            offer_throughput=50000
        )
        print("Container created.")
    except exceptions.CosmosResourceExistsError:
        print("Container already exists.")

# ------------------------
# SYNTHETIC DATA GENERATION
# ------------------------
def generate_synthetic_text():
    topics = ["AI", "Space", "History", "Nature", "Science", "Technology", "Art", "Music", "Philosophy", "Sports"]
    return " ".join(random.choices(topics, k=10))

# ------------------------
# EMBEDDING GENERATION
# ------------------------
def generate_embeddings(text):
    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.embeddings.create(
                input=text,
                model=EMBEDDING_MODEL
            )
            return response.data[0].embedding
        except Exception as e:
            logging.error("Embedding generation failed", exc_info=True)
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)

# ------------------------
# DATA LOADING
# ------------------------
async def generate_and_upload_data():
    credential = DefaultAzureCredential()
    client = CosmosClient(COSMOS_DB_URI, credential)
    db = client.get_database_client(DATABASE_NAME)
    container = db.get_container_client(CONTAINER_NAME)

    semaphore = asyncio.Semaphore(MAX_INGEST_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def process_document():
        item = {
            "id": str(uuid.uuid4()),
            "text": generate_synthetic_text()
        }
        item["embedding"] = await loop.run_in_executor(None, generate_embeddings, item["text"])
        await loop.run_in_executor(None, container.upsert_item, item)

    tasks = []
    for _ in range(NUM_RECORDS):
        async with semaphore:
            tasks.append(asyncio.create_task(process_document()))

    await asyncio.gather(*tasks)
    print(f"Finished ingesting {NUM_RECORDS} documents.")

# ------------------------
# METRICS FUNCTION
# ------------------------
def print_stats(headers, partition_count):
    time_taken = headers['x-ms-documentdb-query-metrics'].split(";")[0]
    ru_charge = float(headers['x-ms-request-charge'])*partition_count
    cost =  (ru_charge/1000000)*0.25
    print("Query Execution Time (ms): ",time_taken.split("=")[1])
    print("RU charge for this Vector Search:", ru_charge)
    print(f"Cost (USD) for this Vector Search in Cosmos DB Serverless: ${cost:.9f}")

# ------------------------
# VECTOR SEARCH FUNCTIONS
# ------------------------
def sql_vector_search(container, query_embedding, top_k=10):
    query = """
        SELECT TOP @top_k c.id, c.text, VectorDistance(c.embedding, @embedding) AS Score
        FROM c
        ORDER BY VectorDistance(c.embedding, @embedding)
    """

    parameters = [
        {"name": "@embedding", "value": query_embedding},
        {"name": "@top_k", "value": top_k}
    ]

    start = time.perf_counter()
    results_iterable = container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        populate_query_metrics=True
    )
    results = list(results_iterable)
    headers = container.client_connection.last_response_headers
    end = time.perf_counter()

    print(f"SQL vector search took {end - start:.2f} seconds")
    print(json.dumps(results, indent=4))
    print_stats(headers, 1)

# Partitioned Concurrent Search
async def fetch_query_results(container, query, parameters, pk_range):
    items = []
    query_iter = container.query_items(
        query=query,
        parameters=parameters,
        partition_key_range_id=pk_range['id'],
        populate_query_metrics=True
    )
    async for item in query_iter:
        items.append(item)
    headers = container.client_connection.last_response_headers
    return items, headers

async def concurrent_query_sample(container, query, parameters):
    pk_ranges = [pk_range async for pk_range in container.client_connection._ReadPartitionKeyRanges(container.container_link)]
    tasks = [fetch_query_results(container, query, parameters, pk_range) for pk_range in pk_ranges]
    results = await asyncio.gather(*tasks)
    return results, pk_ranges

async def concurrent_vector_search(container, query_embedding, top_k=10):
    query = """
        SELECT TOP 10 c.id, c.text, VectorDistance(c.embedding, @query_vector) AS Score
        FROM c
        ORDER BY VectorDistance(c.embedding, @query_vector)
    """
    parameters = [{"name": "@query_vector", "value": query_embedding}]

    start = time.perf_counter()
    partition_results, pk_ranges = await concurrent_query_sample(container, query, parameters)
    flattened_results = [item for sublist, _ in partition_results for item in sublist]
    sorted_results = sorted(flattened_results, key=lambda x: x["Score"])
    end = time.perf_counter()

    print(f"Concurrent fan-out vector search took {end - start:.2f} seconds")
    print(json.dumps(sorted_results[:top_k], indent=4))

    # Get headers from first partition (for simplicity)
    headers = partition_results[0][1]
    print("PK range lenth:", len(pk_ranges))
    print_stats(headers, len(pk_ranges))

# ------------------------
# MAIN FUNCTION
# ------------------------
async def main():
    print("Creating Cosmos DB container (if not exists)...")
    create_cosmos_container()

    print("Generating and uploading synthetic data...")
    await generate_and_upload_data()

    print("Running vector search benchmark...")
    query_text = "Tell me something about AI and Space"
    query_embedding = generate_embeddings(query_text)

    credential = DefaultAzureCredential()
    client = CosmosClient(COSMOS_DB_URI, credential)
    db = client.get_database_client(DATABASE_NAME)
    container = db.get_container_client(CONTAINER_NAME)

    # Run regular cross-partition vector search query
    sql_vector_search(container, query_embedding)

    # Create Async Client for concurrent query
    from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
    async_client = AsyncCosmosClient(COSMOS_DB_URI, credential)
    db_async = async_client.get_database_client(DATABASE_NAME)
    container_async = db_async.get_container_client(CONTAINER_NAME)

    # Run concurrent cross-partition vector search query
    await concurrent_vector_search(container_async, query_embedding)

    await async_client.close()

if __name__ == "__main__":
    asyncio.run(main())
