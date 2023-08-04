# Integrate Open AI Services with Cosmos DB: RAG pattern
This repository provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos DB. The goal is to limit the responses from Open AI services based on recipes stored in Cosmos DB.

## Prerequsites
- Azure Cosmos DB NoSQL Account
    - Create a DataBase and Container with 1000 RU/sec Autoscale provisioned throughput    
- Azure Open AI Service
    - Deploy text-davinci-003 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion
- Azure Cognitive Search Account
  
## Dependencies
This demo is built using .NET and utilizes the following SDKs:
-	Azure Cognitive Search SDK
-	Azure Cosmos DB SDK
-	Azure Open AI Services SDK

## Getting Started
When you run the application for the first time, it will connect to Cosmos DB and report that there are no recipes available, as we have not uploaded any recipes yet.
To begin, follow these steps:
1)	**Upload Documents to Cosmos DB:** Select the first option in the application and hit enter. This option reads documents from the local machine and uploads the JSON files to the Cosmos DB NoSQL account.
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
3)	**Vectorize and Upload Recipes to Azure Cognitive Search:** The JSON data uploaded to Cosmos DB is not yet ready for efficient integration with Open AI. To use the RAG pattern, we need to find relevant recipes from Cosmos DB. Embeddings help us achieve this. To accomplish the task, we will utilize the vector search capability in Azure Cognitive Search to search for embeddings. Firstly, create the required vector search index in Azure Cognitive Search. Then, vectorize the recipes and upload the vectors to Azure Cognitive Search. Additionally, save them into Cosmos DB for future use. Selecting the second option in the application will perform all these activities.

    #### Creating  a Search Index Client for Azure Cognitive Search 
    ```C#
    private SearchIndexClient CreateSearchIndexClient()
    {
      string searchServiceEndPoint = configuration["SearchServiceEndPoint"];
      string adminApiKey = configuration["SearchServiceAdminApiKey"];
    
      SearchIndexClient _indexClient = new SearchIndexClient(new Uri(searchServiceEndPoint), new AzureKeyCredential(adminApiKey));
      return _indexClient;
    }
    ```
  
    ####  Build the Vector Index in Azure Cognitive Search
    ```C#
    private void CreateIndex(string indexName, SearchIndexClient _indexClient)
    {
        _indexClient.CreateOrUpdateIndex(BuildVectorSearchIndex(indexName));
    }

    internal SearchIndex BuildVectorSearchIndex(string name)
    {
        string vectorSearchConfigName = "my-vector-config";

        SearchIndex searchIndex = new(name)
        {
            VectorSearch = new()
            {
                AlgorithmConfigurations =
            {
                new VectorSearchAlgorithmConfiguration(vectorSearchConfigName, "hnsw")
            }
            },
            SemanticSettings = new()
            {

                Configurations =
                {
                   new SemanticConfiguration(_SemanticSearchConfigName, new()
                   {
                       TitleField = new(){ FieldName = "name" },
                       ContentFields =
                       {
                           new() { FieldName = "description" }
                       }
                   })

            },
            },
            Fields =
        {
            new SimpleField("id", SearchFieldDataType.String) { IsKey = true, IsFilterable = true, IsSortable = true, IsFacetable = true },
            new SearchableField("name") { IsFilterable = true, IsSortable = true },
            new SearchableField("description") { IsFilterable = true },
            new SearchField("embedding", SearchFieldDataType.Collection(SearchFieldDataType.Single))
            {
                IsSearchable = true,
                Dimensions = 1536,
                VectorSearchConfiguration = vectorSearchConfigName
            }
        }
        };
        return searchIndex;
    }
    ```

    #### Initialize the Azure Open AI SDK
  	``` C#
    public OpenAIService(string endpoint, string key, string embeddingsDeployment, string CompletionDeployment, string maxTokens)
    {


        openAIEndpoint = endpoint;
        openAIKey = key;
        _openAIEmbeddingDeployment = embeddingsDeployment;
        _openAICompletionDeployment = CompletionDeployment;
        _openAIMaxTokens = int.TryParse(maxTokens, out _openAIMaxTokens) ? _openAIMaxTokens : 8191;


        OpenAIClientOptions clientOptions = new OpenAIClientOptions()
        {
            Retry =
            {
                Delay = TimeSpan.FromSeconds(2),
                MaxRetries = 10,
                Mode = RetryMode.Exponential
            }
        };

        try
        {

            //Use this as endpoint in configuration to use non-Azure Open AI endpoint and OpenAI model names
            if (openAIEndpoint.Contains("api.openai.com"))
                _openAIClient = new OpenAIClient(openAIKey, clientOptions);
            else
                _openAIClient = new(new Uri(openAIEndpoint), new AzureKeyCredential(openAIKey), clientOptions);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OpenAIService Constructor failure: {ex.Message}");
        }
    }
    ```   
   
    #### Generate Embedings using Open AI Service
  	``` C#
    public async Task<float[]?> GetEmbeddingsAsync(dynamic data)
    {
        try
        {
            EmbeddingsOptions options = new EmbeddingsOptions(data)
            {
                Input = data
            };

            var response = await _openAIClient.GetEmbeddingsAsync(openAIEmbeddingDeployment, options);

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
    #### Get the Search client from Index Client of Azure Cognitive Search
    ```C#
    _searchClient = _indexClient.GetSearchClient(_searchIndexName);
    ```
    
    #### Upload embeddings to Azure Cognitive Search for Indexing
  	``` C#
    // Upload documents as a batch.
    public async void UploadandIndexDocuments(List<Recipe> Recipes)
    {
        await _searchClient.IndexDocumentsAsync(IndexDocumentsBatch.Upload(ConvertRecipeToCogSarchDoc(Recipes)));
        
    }    
    ```   

    
5)	**Perform Search:** The third option in the application runs the search based on the user query. The user query is converted to an embedding using the Open AI service. The embedding is then sent to Azure Cognitive Search to perform a vector search. The vector search attempts to find vectors that are close to the supplied vector and returns a list of items. We utilize the search results to retrieve the recipe documents from Cosmos DB, convert them to strings, and provide them to the Open AI service as prompts. During this process, we also include the instructions we want to provide to the Open AI service as prompt. The Open AI service processes the instructions and custom data provided as prompts to generate the response.

    

    #### Performing Vector Search in Azure Cognitive Search
  	```C#
    internal async Task<List<string>> SingleVectorSearch(float[] queryEmbeddings, int searchCount = 5)
    {

        // Perform the vector similarity search  
        var vector = new SearchQueryVector { K = 3, Fields = "embedding", Value = queryEmbeddings.ToArray() };
        var searchOptions = new SearchOptions
        {
            Vector = vector,
            Size = searchCount,
            Select = { "id"},
        };

        SearchResults<SearchDocument> response = await _searchClient.SearchAsync<SearchDocument>(null, searchOptions);

        List<string> ids = new List<string>();
        await foreach (SearchResult<SearchDocument> result in response.GetResultsAsync())
        {
            ids.Add(result.Document["id"].ToString());    
        }
        return ids; 
    }
    ```

    #### Get Recipes from Azure Cosmos DB based on Azure Cogntive Search Result
  	``` C#
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

            ChatMessage systemMessage = new ChatMessage(ChatRole.System, _systemPromptRecipeAssistant + documents);
            ChatMessage userMessage = new ChatMessage(ChatRole.User, userPrompt);


            ChatCompletionsOptions options = new()
            {

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

            Azure.Response<ChatCompletions> completionsResponse = await _openAIClient.GetChatCompletionsAsync(_openAICompletionDeployment, options);

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
