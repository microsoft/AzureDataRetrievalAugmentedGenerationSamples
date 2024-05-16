using Azure.AI.OpenAI;
using Microsoft.Azure.Cosmos;
using Microsoft.Azure.Cosmos.Fluent;
using Microsoft.Azure.Cosmos.Serialization.HybridRow.Schemas;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using Container = Microsoft.Azure.Cosmos.Container;
using PartitionKey = Microsoft.Azure.Cosmos.PartitionKey;

namespace CosmosRecipeGuide.Services;

/// <summary>
/// Service to access Azure Cosmos DB for NoSQL.
/// </summary>
public class CosmosDbService
{
    private readonly Container _container;
    CosmosClient? _client;
    Database? _database;

    /// <summary>
    /// Creates a new instance of the service.
    /// </summary>
    /// <param name="endpoint">Endpoint URI.</param>
    /// <param name="key">Account key.</param>
    /// <param name="databaseName">Name of the database to access.</param>
    /// <param name="containerName">Name of the container to access.</param>
    /// <exception cref="ArgumentNullException">Thrown when endpoint, key, databaseName, or containerName is either null or empty.</exception>
    /// <remarks>
    /// This constructor will validate credentials and create a service client instance.
    /// </remarks>
    public CosmosDbService(string endpoint, string key, string databaseName, string containerName)
    {
        ArgumentNullException.ThrowIfNullOrEmpty(endpoint);
        ArgumentNullException.ThrowIfNullOrEmpty(key);
        ArgumentNullException.ThrowIfNullOrEmpty(databaseName);
        ArgumentNullException.ThrowIfNullOrEmpty(containerName);


        CosmosSerializationOptions options = new()
        {
            PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase
        };

        _client = new CosmosClientBuilder(endpoint, key)
            .WithSerializerOptions(options)
            .Build();

        _database = _client?.GetDatabase(databaseName);
        Container? container = _database?.GetContainer(containerName);


        _container = container ??
            throw new ArgumentException("Unable to connect to existing Azure Cosmos DB container or database.");
    }

    public async Task<bool> CheckCollectionExistsAsync()
    {
        try
        {
            // Check if the container exists
            return await _container.ReadContainerAsync() != null;
        }
        catch (Exception ex)
        {
            return false;
        }
    }


    public async Task<bool> CreateCosmosContainerAsync(string databaseName, string containerName)
    {
        try
        {
            ThroughputProperties throughputProperties = ThroughputProperties.CreateAutoscaleThroughput(1000);

            // Define new container properties including the vector indexing policy
            ContainerProperties properties = new ContainerProperties(id: containerName, partitionKeyPath: "/id")
            {
                // Set the default time to live for cache items to 1 day
                DefaultTimeToLive = 86400,

                // Define the vector embedding container policy
                VectorEmbeddingPolicy = new(
                new Collection<Embedding>(
                [
                    new Embedding()
                {
                    Path = "/vectors",
                    DataType = VectorDataType.Float32,
                    DistanceFunction = DistanceFunction.Cosine,
                    Dimensions = 1536
                }
                ])),
                IndexingPolicy = new IndexingPolicy()
                {
                    // Define the vector index policy
                    VectorIndexes = new()
                {
                    new VectorIndexPath()
                    {
                        Path = "/vectors",
                        Type = VectorIndexType.QuantizedFlat
                    }
                }
                }
            };

            // Create the container
            Container container = _database.CreateContainerIfNotExistsAsync(properties, throughputProperties).Result;

            return true;
        }
        catch (Exception ex)
        {
            return false;
        }
    }


    public async Task<List<Recipe>> SingleVectorSearch(float[] vectors, double similarityScore)
    {
        
        string queryText = @"SELECT Top 3 x.name,x.description, x.ingredients, x.cuisine,x.difficulty, x.prepTime,x.cookTime,x.totalTime,x.servings, x.similarityScore
                            FROM (SELECT c.name,c.description, c.ingredients, c.cuisine,c.difficulty, c.prepTime,c.cookTime,c.totalTime,c.servings,
                                VectorDistance(c.vectors, @vectors, false) as similarityScore FROM c) x
                                    WHERE x.similarityScore > @similarityScore ORDER BY x.similarityScore desc";

        var queryDef = new QueryDefinition(
                query: queryText)
            .WithParameter("@vectors", vectors)
            .WithParameter("@similarityScore", similarityScore);

        using FeedIterator<Recipe> resultSet = _container.GetItemQueryIterator<Recipe>(queryDefinition: queryDef);

        List<Recipe> recipes = new List<Recipe>();
        while (resultSet.HasMoreResults)
        {
            FeedResponse<Recipe> response = await resultSet.ReadNextAsync();
            recipes.AddRange(response);
        }
        return recipes;
    }

    /// <summary>
    /// Gets a list of all recipes where embeddings are null.
    /// </summary>
    public async Task<List<Recipe>> GetRecipesToVectorizeAsync()
    {
        QueryDefinition query = new QueryDefinition("SELECT * FROM c WHERE IS_ARRAY(c.vectors)=false");

        FeedIterator<Recipe> results = _container.GetItemQueryIterator<Recipe>(query);

        List<Recipe> output = new();
        while (results.HasMoreResults)
        {
            FeedResponse<Recipe> response = await results.ReadNextAsync();
            output.AddRange(response);
        }
        return output;
    }

    /// <summary>
    /// Gets a count of all recipes based on embeddings status.
    /// </summary>
    public async Task<int> GetRecipeCountAsync(bool withEmbedding)
    {
        QueryDefinition query = new QueryDefinition("SELECT value Count(c.id) FROM c WHERE IS_ARRAY(c.vectors)=@status")
            .WithParameter("@status", withEmbedding);

        // Execute the query and retrieve the results
        var queryResultSetIterator = _container.GetItemQueryIterator<int>(query);
        var queryResultSet = await queryResultSetIterator.ReadNextAsync();

        // Retrieve the count value from the results
        return queryResultSet.FirstOrDefault();
    }

    public async Task AddRecipesAsync( List<Recipe> recipes)
    {
        BulkOperations<Recipe> bulkOperations = new BulkOperations<Recipe>(recipes.Count);
        foreach (Recipe recipe in recipes)
        {
            bulkOperations.Tasks.Add(CaptureOperationResponse(_container.CreateItemAsync(recipe, new PartitionKey(recipe.id)), recipe));
        }
        BulkOperationResponse<Recipe> bulkOperationResponse = await bulkOperations.ExecuteAsync();
    }


    public async Task UpdateRecipesAsync(Dictionary<string, float[]> dictInput)
    {
        BulkOperations<Recipe> bulkOperations = new BulkOperations<Recipe>(dictInput.Count);
        foreach (KeyValuePair<string, float[]> entry in dictInput) 
        {
            await _container.PatchItemAsync<Recipe>(entry.Key,new PartitionKey(entry.Key), patchOperations: new[] { PatchOperation.Add("/vectors", entry.Value)});
        }
    }


    private class BulkOperations<T>
    {
        public readonly List<Task<OperationResponse<T>>> Tasks;

        private readonly Stopwatch stopwatch = Stopwatch.StartNew();

        public BulkOperations(int operationCount)
        {
            this.Tasks = new List<Task<OperationResponse<T>>>(operationCount);
        }

        public async Task<BulkOperationResponse<T>> ExecuteAsync()
        {
            await Task.WhenAll(this.Tasks);
            this.stopwatch.Stop();
            return new BulkOperationResponse<T>()
            {
                TotalTimeTaken = this.stopwatch.Elapsed,
                TotalRequestUnitsConsumed = this.Tasks.Sum(task => task.Result.RequestUnitsConsumed),
                SuccessfulDocuments = this.Tasks.Count(task => task.Result.IsSuccessful),
                Failures = this.Tasks.Where(task => !task.Result.IsSuccessful).Select(task => (task.Result.Item, task.Result.CosmosException)).ToList()
            };
        }
    }
    

    public class BulkOperationResponse<T>
    {
        public TimeSpan TotalTimeTaken { get; set; }
        public int SuccessfulDocuments { get; set; } = 0;
        public double TotalRequestUnitsConsumed { get; set; } = 0;

        public IReadOnlyList<(T, Exception)>? Failures { get; set; }
    }

    public class OperationResponse<T>
    {
        public T? Item { get; set; }
        public double RequestUnitsConsumed { get; set; } = 0;
        public bool IsSuccessful { get; set; }
        public Exception? CosmosException { get; set; }
    }

    private static async Task<OperationResponse<T>> CaptureOperationResponse<T>(Task<ItemResponse<T>> task, T item)
    {
        try
        {
            ItemResponse<T> response = await task;
            return new OperationResponse<T>()
            {
                Item = item,
                IsSuccessful = true,
                RequestUnitsConsumed = task.Result.RequestCharge
            };
        }
        catch (Exception ex)
        {
            if (ex is CosmosException cosmosException)
            {
                return new OperationResponse<T>()
                {
                    Item = item,
                    RequestUnitsConsumed = cosmosException.RequestCharge,
                    IsSuccessful = false,
                    CosmosException = cosmosException
                };
            }

            return new OperationResponse<T>()
            {
                Item = item,
                IsSuccessful = false,
                CosmosException = ex
            };
        }
    }


}