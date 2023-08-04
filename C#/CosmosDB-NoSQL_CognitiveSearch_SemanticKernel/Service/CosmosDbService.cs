using Microsoft.Azure.Cosmos;
using Microsoft.Azure.Cosmos.Fluent;
using System.ComponentModel;
using System.Diagnostics;
using Container = Microsoft.Azure.Cosmos.Container;

namespace CosmosRecipeGuide.Services;

/// <summary>
/// Service to access Azure Cosmos DB for NoSQL.
/// </summary>
public class CosmosDbService
{
    private readonly Container _container;

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

        CosmosClient client = new CosmosClientBuilder(endpoint, key)
            .WithSerializerOptions(options)
            .Build();

        Database? database = client?.GetDatabase(databaseName);
        Container? container = database?.GetContainer(containerName);

        _container = container ??
            throw new ArgumentException("Unable to connect to existing Azure Cosmos DB container or database.");
    }


    /// <summary>
    /// Gets a list of all recipes where embeddings are null.
    /// </summary>
    public async Task<List<Recipe>> GetRecipesToVectorizeAsync()
    {
        QueryDefinition query = new QueryDefinition("SELECT * FROM c WHERE IS_ARRAY(c.embedding)=false");

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
        QueryDefinition query = new QueryDefinition("SELECT value Count(c.id) FROM c WHERE c.embeddingStatus=@status")
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

    public async Task<List<Recipe>> GetRecipesAsync(List<string> ids)
    {
        string querystring= "SELECT * FROM c WHERE c.id IN(" + string.Join(",", ids.Select(id => $"'{id}'")) + ")";

        QueryDefinition query = new QueryDefinition(querystring);

        FeedIterator<Recipe> results = _container.GetItemQueryIterator<Recipe>(query);

        List<Recipe> output = new();
        while (results.HasMoreResults)
        {
            FeedResponse<Recipe> response = await results.ReadNextAsync();
            output.AddRange(response);
        }
        return output;
    }

    public async Task UpdateRecipesAsync(List<string> docsToUpdate)
    {
        BulkOperations<Recipe> bulkOperations = new BulkOperations<Recipe>(docsToUpdate.Count);
        foreach ( string entry in docsToUpdate) 
        {
            await _container.PatchItemAsync<Recipe>(entry,new PartitionKey(entry), patchOperations: new[] { PatchOperation.Add("/embeddingStatus", true)});
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