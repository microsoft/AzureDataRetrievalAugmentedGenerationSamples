using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Azure.AI.OpenAI;
using CosmosRecipeGuide.Services;
//using Microsoft.Azure.Cosmos;
using MongoDB.Bson;
using MongoDB.Driver;
using Newtonsoft.Json.Linq;
using MongoDB.Bson.Serialization;

namespace CosmosRecipeGuide.Service
{
    internal class CosmosDBMongoVCoreService
    {

        private readonly MongoClient _client;
        private readonly IMongoDatabase _database;

        
        private readonly IMongoCollection<BsonDocument> _recipeCollection;
        private readonly int _maxVectorSearchResults = default;


        /// <summary>
        /// Creates a new instance of the service.
        /// </summary>
        /// <param name="endpoint">Endpoint URI.</param>
        /// <param name="key">Account key.</param>
        /// <param name="databaseName">Name of the database to access.</param>
        /// <param name="collectionNames">Names of the collections for this retail sample.</param>
        /// <exception cref="ArgumentNullException">Thrown when endpoint, key, databaseName, or collectionNames is either null or empty.</exception>
        /// <remarks>
        /// This constructor will validate credentials and create a service client instance.
        /// </remarks>
        public CosmosDBMongoVCoreService(string connection, string databaseName, string collectionName, string maxVectorSearchResults)
        {
            ArgumentException.ThrowIfNullOrEmpty(connection);
            ArgumentException.ThrowIfNullOrEmpty(databaseName);
            ArgumentException.ThrowIfNullOrEmpty(collectionName);
            ArgumentException.ThrowIfNullOrEmpty(maxVectorSearchResults);


            _client = new MongoClient(connection);
            _database = _client.GetDatabase(databaseName);
            _maxVectorSearchResults = int.TryParse(maxVectorSearchResults, out _maxVectorSearchResults) ? _maxVectorSearchResults : 10;
            _recipeCollection = _database.GetCollection<BsonDocument>(collectionName);

        }

        /// <summary>
        /// Gets a list of all recipes where embeddings are null.
        /// </summary>
        public async Task<List<Recipe>> GetRecipesToVectorizeAsync()
        {

            var filter = Builders<BsonDocument>.Filter.Type("embedding", BsonType.Null);
            //var recipes = _recipeCollection.Find(filter).ToList().ConvertAll(bsonDocument => BsonToRecipe(bsonDocument));
            var recipes = _recipeCollection.Find(filter).ToList().ConvertAll(bsonDocument => BsonSerializer.Deserialize<Recipe>(bsonDocument));

            return recipes;

        }


        /// <summary>
        /// Gets a count of all recipes based on embeddings status.
        /// </summary>
        public async Task<long> GetRecipeCountAsync(bool withEmbedding)
        {
            FilterDefinition<BsonDocument> filter;
            if (withEmbedding)
                filter = Builders<BsonDocument>.Filter.Type("embedding", BsonType.Array);
            else
                filter = Builders<BsonDocument>.Filter.Type("embedding", BsonType.Null);

           return _recipeCollection.Find(filter).ToList().Count;

        }
               
        public bool CheckIndexIfExists(string vectorIndexName)
        {
            try
            {

                //Find if vector index exists in vectors collection
                using (IAsyncCursor<BsonDocument> indexCursor = _recipeCollection.Indexes.List())
                {
                    return indexCursor.ToList().Any(x => x["name"] == vectorIndexName);                   
                }

            }
            catch (MongoException ex)
            {
                Console.WriteLine("MongoDbService InitializeVectorIndex: " + ex.Message);
                throw;
            }
        }

        public void CreateVectorIndexIfNotExists(string vectorIndexName)
        {

            try
            {

                //Find if vector index exists in vectors collection
                using (IAsyncCursor<BsonDocument> indexCursor = _recipeCollection.Indexes.List())
                {
                    bool vectorIndexExists = indexCursor.ToList().Any(x => x["name"] == vectorIndexName);
                    if (!vectorIndexExists)
                    {
                        BsonDocumentCommand<BsonDocument> command = new BsonDocumentCommand<BsonDocument>(
                        BsonDocument.Parse(@"
                            { createIndexes: 'Recipe', 
                              indexes: [{ 
                                name: 'vectorSearchIndex', 
                                key: { embedding: 'cosmosSearch' }, 
                                cosmosSearchOptions: { kind: 'vector-ivf', numLists: 5, similarity: 'COS', dimensions: 1536 } 
                              }] 
                            }"));

                        BsonDocument result = _database.RunCommand(command);
                        if (result["ok"] != 1)
                        {
                            Console.WriteLine("CreateIndex failed with response: " + result.ToJson());
                        }
                    }
                }

            }
            catch (MongoException ex)
            {
                Console.WriteLine("MongoDbService InitializeVectorIndex: " + ex.Message);
                throw;
            }

        }

        public async Task<List<Recipe>> VectorSearchAsync(float[] queryVector)
        {
            List<string> retDocs = new List<string>();

            string resultDocuments = string.Empty;

            try
            {
                //Search Azure Cosmos DB for MongoDB vCore collection for similar embeddings
                //Project the fields that are needed
                BsonDocument[] pipeline = new BsonDocument[]
                {   
                    BsonDocument.Parse($"{{$search: {{cosmosSearch: {{ vector: [{string.Join(',', queryVector)}], path: 'embedding', k: {_maxVectorSearchResults}}}, returnStoredSource:true}}}}"),
                    BsonDocument.Parse($"{{$project: {{embedding: 0}}}}"),
                };

                var bsonDocuments = await _recipeCollection.Aggregate<BsonDocument>(pipeline).ToListAsync();

                var recipes = bsonDocuments.ToList().ConvertAll(bsonDocument => BsonSerializer.Deserialize<Recipe>(bsonDocument)); 
                return recipes;
            }
            catch (MongoException ex)
            {
                Console.WriteLine($"Exception: VectorSearchAsync(): {ex.Message}");
                throw;
            }

        }

        public async Task UpsertVectorAsync(Recipe recipe)
        {

            BsonDocument document = recipe.ToBsonDocument();

            if (!document.Contains("_id"))
            {
                Console.WriteLine("UpsertVectorAsync: Document does not contain _id.");
                throw new ArgumentException("UpsertVectorAsync: Document does not contain _id.");
            }

            string? _idValue = document["_id"].ToString();


            try
            {
                var filter = Builders<BsonDocument>.Filter.Eq("_id", _idValue);
                var options = new ReplaceOptions { IsUpsert = true };
                await _recipeCollection.ReplaceOneAsync(filter, document, options);

            }
            catch (Exception ex)
            {

                Console.WriteLine($"Exception: UpsertVectorAsync(): {ex.Message}");
                throw;
            }

        }

    }
}
