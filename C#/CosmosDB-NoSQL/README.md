# Integrate Open AI Services with Cosmos DB: RAG pattern
This repository provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos DB NoSQL API. The goal is to limit the responses from Open AI services based on recipes stored in Cosmos DB.

## Prerequsites
- Azure Cosmos DB NoSQL Account
    - Create a DataBase    
- Azure Open AI Service
    - Deploy text-embedding-ada-002 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion
  
## Dependencies
This demo is built using .NET and utilizes the following SDKs:
-	Azure Cosmos DB SDK
-	Azure Open AI Services SDK
-   Enable preview feature on CosmosDB using  the below CLI

```
        az cosmosdb update --resource-group '<RG Name>' --name '<Cosms Account Name>'  --capabilities EnableNoSQLVectorSearch
```


## Getting Started
When you run the application for the first time, it will connect to Cosmos DB and report that the container  recipes is not available.
To begin, follow these steps:
1)  **Prepare Cosmos DB Container for Vector Search:** Create a new container with Vector Index and Vector Embedding Policy. The container is created with 1000 RU/sec Autoscale provisioned throughput.

```csharp
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

```


2)	**Upload Documents to Cosmos DB:** Select this option to read documents from the local machine and upload the JSON files to the Cosmos DB NoSQL account.
    #### Parsing files from Local Folder
    ``` C#
    public static List<Recipe> ParseDocuments(string Folderpath)
    {
      List<Recipe> ret = new List<Recipe>();
    
      Directory.GetFiles(Folderpath).ToList().ForEach(f =>
          {
              var jsonString= System.IO.File.ReadAllText(f);
              Recipe recipe = JsonConvert.DeserializeObject<Recipe>(jsonString);
              recipe.id = recipe.name.ToLower().Replace(" ","");
              ret.Add(recipe);
    
          }
      );
      return ret;    
    }
    
    ```
    ####  Uploading Documents in Bulk to Azure Cosmos DB
    ```C#
    public async Task AddRecipesAsync( List<Recipe> recipes)
    {
        BulkOperations<Recipe> bulkOperations = new BulkOperations<Recipe>(recipes.Count);
        foreach (Recipe recipe in recipes)
        {
            bulkOperations.Tasks.Add(CaptureOperationResponse(_container.CreateItemAsync(recipe, new PartitionKey(recipe.id)), recipe));
        }
        BulkOperationResponse<Recipe> bulkOperationResponse = await bulkOperations.ExecuteAsync();
    }
    ```
3)	**Vectorize and Upload Recipes to Azure Cognitive Search:** The JSON data uploaded to Cosmos DB is not yet ready for efficient integration with Open AI. To use the RAG pattern, we need to find relevant recipes from Cosmos DB. Embeddings help us achieve this. To accomplish the task, we will utilize the vector search capability in Azure Cosmos DB NoSQL API to search for embeddings. Vectorize the recipes and save them into Cosmos DB for future use. 

   
    #### Generate Embedings using Open AI Service
  	``` C#
    public async Task<float[]?> GetEmbeddingsAsync(dynamic data)
    {
        try
        {
            EmbeddingsOptions embeddingsOptions = new()
            {
                DeploymentName = _openAIEmbeddingDeployment,
                Input = { data },
            };
            var response = await _openAIClient.GetEmbeddingsAsync(embeddingsOptions);
          
            Embeddings embeddings = response.Value;
    
            float[] embedding = embeddings.Data[0].Embedding.ToArray();
    
            return embedding;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"GetEmbeddingsAsync Exception: {ex.Message}");
            return null;
        }
    }
    ```

    
    #### Upload embeddings to Azure Cosmos DB
  	``` C#
    public async Task UpdateRecipesAsync(Dictionary<string, float[]> dictInput)
    {
        BulkOperations<Recipe> bulkOperations = new BulkOperations<Recipe>(dictInput.Count);
        foreach (KeyValuePair<string, float[]> entry in dictInput) 
        {
            await _container.PatchItemAsync<Recipe>(entry.Key,new PartitionKey(entry.Key), patchOperations: new[] { PatchOperation.Add("/vectors", entry.Value)});
        }
    }
    ```   

    
4)	**Perform Search:** This option in the application runs the search based on the user query. The user query is converted to an embedding using the Open AI service. The embedding is then used to perform a vector search. The vector search attempts to find vectors that are close to the supplied vector and returns a list of items. The search results are converted to strings, and sent to the Open AI service as prompts. During this process, we also include the instructions we want to provide to the Open AI service as prompt. The Open AI service processes the instructions and custom data provided as prompts to generate the response.

    

    #### Performing Vector Search in Azure Cosmos DB NoSQL
  	```C#
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
    ```
    
   
    #### Prompt Engineering to make sure Open AI service limits the response to supplied recipes
    ```C#
    //System prompts to send with user prompts to instruct the model for chat session
    private readonly string _systemPromptRecipeAssistant = @"
        You are an intelligent assistant for Contoso Recipes. 
        You are designed to provide helpful answers to user questions about 
        recipes, cooking instructions provided in JSON format below.
  
        Instructions:
        - Only answer questions related to the recipe provided below,
        - Don't reference any recipe not provided below.
        - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
        - Your response  should be complete. 
        - List the Name of the Recipe at the start of your response folowed by step by step cooking instructions
        - Assume the user is not an expert in cooking.
        - Format the content so that it can be printed to the Command Line console;
        - In case there are more than one recipes you find let the user pick the most appropiate recipe.";
     ```
    
    #### Generate Chat Completion based on Prompt and Custom Data 
    ``` C#
     public async Task<(string response, int promptTokens, int responseTokens)> GetChatCompletionAsync(string userPrompt, string documents)
     {
    
         try
         {
    
             var systemMessage = new ChatRequestSystemMessage(_systemPromptRecipeAssistant + documents);
             var userMessage = new ChatRequestUserMessage(userPrompt);
    
    
             ChatCompletionsOptions options = new()
             {
                 DeploymentName= _openAICompletionDeployment,
                 Messages =
                 {
                     systemMessage,
                     userMessage
                 },
                 MaxTokens = _openAIMaxTokens,
                 Temperature = 0.5f, //0.3f,
                 NucleusSamplingFactor = 0.95f, 
                 FrequencyPenalty = 0,
                 PresencePenalty = 0
             };
    
             Azure.Response<ChatCompletions> completionsResponse = await _openAIClient.GetChatCompletionsAsync(options);
    
             ChatCompletions completions = completionsResponse.Value;
    
             return (
                 response: completions.Choices[0].Message.Content,
                 promptTokens: completions.Usage.PromptTokens,
                 responseTokens: completions.Usage.CompletionTokens
             );
    
         }
         catch (Exception ex)
         {
    
             string message = $"OpenAIService.GetChatCompletionAsync(): {ex.Message}";
             Console.WriteLine(message);
             throw;
    
         }
     }
    ```
