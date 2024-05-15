# Integrate Open AI Services with Cosmos DB: RAG pattern

This repository provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos DB. The goal is to limit the responses from Open AI services based on recipes stored in Cosmos DB.

### Prerequisites

- Azure Cosmos DB NoSQL Account
    - Create a DataBase and Container with 1000 RU/sec Autoscale provisioned throughput
- Azure Open AI Service
    - Deploy text-davinci-003 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion


### Installation
``` bash 
mvn install
```

### Run

Before running the application, you need to set environment variables. Either export them in command line or set system variables:

```bash
    export COSMOS_URI="URI of your Cosmos DB account"
    export COSMOS_KEY="KEY of your Cosmos DB account"
    export COSMOS_DATABASE="name of a database you have created"
    export COSMOS_CONTAINER="name of a container in above database, partitioned by id"
    export RECIPE_LOCAL_FOLDER="the full path to the Recipe folder in this project e.g. C:CosmosDemo\OpenAICognitiveSearch\Recipe"
    export OPENAI_ENDPOINT="endpoint for your Azure OpenAI account"
    export OPENAI_KEY="key for your Azure OpenAI account"
    export OPENAI_EMBEDDING_DEPLOYMENT="deployment id for your Azure OpenAI chat embeddings"
    export OPENAI_COMPLETIONS_DEPLOYMENT="deployment is for your Azure OpenAI chat completions"
```

Then run the app:

```bash
mvn exec:java   
```

## Getting Started
When you run the application for the first time, it will connect to Cosmos DB and report that there are no recipes available, as we have not uploaded any recipes yet.
To begin, follow these steps:

1) **Vectorize and upload documents to Cosmos DB:** Select the first option in the application and hit enter. This option reads documents from the local machine, vectorizes and uploads the JSON files to Cosmos DB NoSQL container.

2) **Ask AI assistent:** Select the second option to ask for a recipe. A vector search will be performed against Azure Cosmos DB NoSQL API using vector search with DiskANN.


####  Build Vector embedding and index policy in Azure Cosmos DB NoSQL API
<details>
<summary>Click to show/hide</summary>

``` Java
    CosmosContainerProperties collectionDefinition = new CosmosContainerProperties(containerName, "/id");

    //set vector embedding policy
    CosmosVectorEmbeddingPolicy cosmosVectorEmbeddingPolicy = new CosmosVectorEmbeddingPolicy();
    CosmosVectorEmbedding embedding = new CosmosVectorEmbedding();
    embedding.setPath("/embedding");
    embedding.setDataType(CosmosVectorDataType.FLOAT32);
    embedding.setDimensions(8L);
    embedding.setDistanceFunction(CosmosVectorDistanceFunction.COSINE);
    cosmosVectorEmbeddingPolicy.setCosmosVectorEmbeddings(Arrays.asList(embedding));
    collectionDefinition.setVectorEmbeddingPolicy(cosmosVectorEmbeddingPolicy);

    //set vector indexing policy
    IndexingPolicy indexingPolicy = new IndexingPolicy();
    indexingPolicy.setIndexingMode(IndexingMode.CONSISTENT);
    ExcludedPath excludedPath = new ExcludedPath("/*");
    indexingPolicy.setExcludedPaths(Collections.singletonList(excludedPath));
    IncludedPath includedPath1 = new IncludedPath("/name/?");
    IncludedPath includedPath2 = new IncludedPath("/description/?");
    indexingPolicy.setIncludedPaths(ImmutableList.of(includedPath1, includedPath2));
    CosmosVectorIndexSpec cosmosVectorIndexSpec = new CosmosVectorIndexSpec();
    cosmosVectorIndexSpec.setPath("/embedding");
    cosmosVectorIndexSpec.setType(CosmosVectorIndexType.DISK_ANN.toString());
    indexingPolicy.setVectorIndexes(Arrays.asList(cosmosVectorIndexSpec));
    collectionDefinition.setIndexingPolicy(indexingPolicy);

```
</details>

#### Initialize the Azure Open AI SDK
<details>
<summary>Click to show/hide</summary>

``` Java
    public OpenAIService( String endpoint,
                          String key,
                          String embeddingsDeployment,
                          String completionDeployment,
                          int maxTokens) {
    
        this.openAIEmbeddingDeployment = embeddingsDeployment;
        this.openAICompletionDeployment = completionDeployment;
        this.openAIMaxTokens = maxTokens;

        RetryOptions retryOptions = new RetryOptions(
          new ExponentialBackoffOptions()
            .setMaxRetries(10)
            .setMaxDelay(Duration.of(2, ChronoUnit.SECONDS))
        );

        if (endpoint.contains("openai.azure.com")) {
          this.openAIClient = new OpenAIClientBuilder()
            .endpoint(endpoint)
            .credential(new AzureKeyCredential(key))
            .retryOptions(retryOptions)
            .buildAsyncClient();
        } else {
          this.openAIClient = new OpenAIClientBuilder()
            .endpoint(endpoint)
            .credential(new NonAzureOpenAIKeyCredential(key))
            .retryOptions(retryOptions)
            .buildAsyncClient();
        }
    }

```   
</details>

#### Generate Embedings using Open AI Service
<details>
<summary>Click to show/hide</summary>

``` Java
    public List<Double> getEmbeddings(String query) {
        try {
            EmbeddingsOptions options = new EmbeddingsOptions(List.of(query));
            options.setUser("");

            var response = openAIClient.getEmbeddings(openAIEmbeddingDeployment, options).block();

            List<EmbeddingItem> embeddings = response.getData();

            return embeddings.get(0).getEmbedding().stream().toList();
        } catch (Exception ex) {
            log.error("GetEmbeddingsAsync Exception:", ex);
            ex.printStackTrace();
            return null;
        }
    }

```

</details>


#### Prompt Engineering to make sure Open AI service limits the response to supplied recipes
<details>
<summary>Click to show/hide</summary>

``` Java
    private String systemPromptRecipeAssistant = """
            You are an intelligent assistant for Contoso Recipes. 
            You are designed to provide helpful answers to user questions about using
            recipes, cooking instructions only using the provided JSON strings.

            Instructions:
            - In case a recipe is not provided in the prompt politely refuse to answer all queries regarding it. 
            - Never refer to a recipe not provided as input to you.
            - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
            - Your response  should be complete. 
            - List the Name of the Recipe at the start of your response folowed by step by step cooking instructions
            - Assume the user is not an expert in cooking.
            - Format the content so that it can be printed to the Command Line 
            - In case there are more than one recipes you find let the user pick the most appropiate recipe. """;

 ```
</details>

#### Generate Chat Completion based on Prompt and Custom Data
<details>
<summary>Click to show/hide</summary>

``` Java
    public String getChatCompletionAsync(String userPrompt, String documents) {


        ChatMessage systemMessage = new ChatMessage(ChatRole.SYSTEM);
        systemMessage.setContent(systemPromptRecipeAssistant + documents);
        ChatMessage userMessage = new ChatMessage(ChatRole.USER);
        userMessage.setContent(userPrompt);


        ChatCompletionsOptions options = new ChatCompletionsOptions(List.of(userMessage, systemMessage));
        options.setMaxTokens(openAIMaxTokens);
        options.setTemperature(0.5);
        options.setFrequencyPenalty(0d);
        options.setPresencePenalty(0d);
        options.setN(1);
        options.setLogitBias(new HashMap<>());
        options.setUser("");


        ChatCompletions completions = openAIClient.getChatCompletions(openAICompletionDeployment, options).block();

        return completions.getChoices().get(0).getMessage().getContent();

    }

```
</details>