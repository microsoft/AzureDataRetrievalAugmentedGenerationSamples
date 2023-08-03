# Integrate Open AI Services with Cosmos DB: RAG pattern
This repository provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos DB using Semantic Kernel. The goal is to limit the responses from Open AI services based on recipes stored in Cosmos DB.

## Prerequsites
- Azure Cosmos DB NoSQL Account
    - Create a DataBase and Container with 1000 RU/sec Autoscale provisioned throughput    
- Azure Open AI Service
    - Deploy text-davinci-003 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion
- Azure Cognitive Search Account
  
## Dependencies
This demo is built using .NET and utilizes the following SDKs:
-	Microsoft Semantic Kernel SDK
-	Azure Cosmos DB SDK


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

3)	**Vectorize and Upload Recipes to Azure Cognitive Search:** The JSON data uploaded to Cosmos DB is not yet ready for efficient integration with Open AI. To use the RAG pattern, we need to find relevant recipes from Cosmos DB. Embeddings help us achieve this. To accomplish the task, we will utilize the vector search capability in Azure Cognitive Search to search for embeddings. Semantic Kernel will
    - Create the required vector search index in Azure Cognitive Search
    - Vectorize the recipes and upload the vectors to Azure Cognitive Search.
    
    Selecting the second option in the application will perform all these activities.

    #### Generating Embeddings  and saving it to Azure Cognitive Search

    ```C#
   
    public async Task SaveEmbeddingsAsync(string data, string id)
        {
            try
            {
                await kernel.Memory.SaveReferenceAsync(
                   collection: MemoryCollectionName,
                   externalSourceName: "Recipe",
                   externalId: id,
                   description: data,
                   text: data);

            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.ToString());   
            }
        }

    ```   


    
4)	**Perform Search:** The third option in the application runs the search based on the user query. Semantic Kernel will
    - Convert the user query to an embedding using the Open AI service.
    - Send the embedding to Azure Cognitive Search to perform a vector search.
    
    The vector search attempts to find vectors that are close to the supplied vector and returns a list of items. We utilize the search results to retrieve the recipe documents from Cosmos DB, convert them to strings.
    
    Finally  the Semantic Kernel is used generate a  chat completions. During this process, we  include the shortlisted recipes as system message, the user query as user message and the instructions are provided in the chat  constructor.
    

    #### Performing Vector Search in Azure Cognitive Search
  	```C#
     public async Task<List<string>> SearchEmbeddingsAsync(string query)
        {
            var memories = kernel.Memory.SearchAsync(MemoryCollectionName, query, limit: 2, minRelevanceScore: 0.5);

            List<string> result = new List<string>();   
            int i = 0;
            await foreach (MemoryQueryResult memory in memories)
            {
                result.Add(memory.Metadata.Id);
            }
            return result;
        }urn ids; 
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
    public async Task<string> GenerateCompletionAsync(string userPrompt, string  recipeData)
        {
            string systemPromptRecipeAssistant = @"
            You are an intelligent assistant for Contoso Recipes. 
            You are designed to provide helpful answers to user questions about using
            recipes, cooking instructions only using the provided JSON strings.
            INSTRUCTIONS
            - In case a recipe is not provided in the prompt politely refuse to answer all queries regarding it. 
            - Never refer to a recipe not provided as input to you.
            - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
            - Your response  should be complete. 
            - When replying with a recipe list the Name of the Recipe at the start of your response folowed by step by step cooking instructions
            - Assume the user is not an expert in cooking.
            - Format the content so that it can be printed to the Command Line 
            - In case there are more than one recipes you find let the user pick the most appropiate recipe.";

            // Client used to request answers to gpt-3.5 - turbo
            var chatCompletion = kernel.GetService<IChatCompletion>();

            var chatHistory = chatCompletion.CreateNewChat(systemPromptRecipeAssistant);

            // add shortlisted recipes as system message
            chatHistory.AddSystemMessage(recipeData);

            // send user promt as user message
            chatHistory.AddUserMessage(userPrompt);

            // Finally, get the response from AI
            string answer = await chatCompletion.GenerateMessageAsync(chatHistory);


            return answer;
        }
    ```
