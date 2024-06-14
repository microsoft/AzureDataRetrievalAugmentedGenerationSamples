# Use Azure Cosmos DB NoSQL API with Langchain in Java.

This sample provides a demo showcasing the usage of the RAG pattern for integrating Azure Open AI services with custom data in Azure Cosmos NoSQL API with [vector search using DiskANN index](https://learn.microsoft.com/azure/cosmos-db/nosql/vector-search) and [langchain framework for java](https://github.com/langchain4j/langchain4j).

### Prerequisites

- Azure Cosmos DB NoSQL API Account
    - Azure Cosmos DB NoSQL API endpoint
    - Azure Cosmos DB NoSQL API key
- Azure Open AI Service
    - Deploy text-davinci-003 model for Embeding
    - Deploy gpt-35-turbo model for Chat Completion


### Installation
``` bash 
mvn clean install
```

### Run

Before running the application, you need to set environment variables. Either export them in command line or set system variables:

```bash
    export COSMOSDB_ENDPOINT="Azure Cosmos DB NoSQL API endpoint"
    export COSMOSDB_KEY="Azure Cosmos DB NoSQL API key"
    export AZURE_OPENAI_ENDPOINT="endpoint for your Azure OpenAI account"
    export AZURE_OPENAI_APIKEY="key for your Azure OpenAI account"
    export AZURE_OPENAI_CHATDEPLOYMENTID="deployment id for your Azure OpenAI chat embeddings"
    export AZURE_OPENAI_EMBEDDINGDEPLOYMENTID="deployment is for your Azure OpenAI chat completions"
```

Then run the app:

```bash
mvn exec:java   
```

## Getting Started
When you run the application for the first time, it will read and vectorize docs in the `PDF_docs` folder (you can add your own pdf or txt docs here), and insert them into Cosmos DB NoSQL API vector store. To begin, just ask a question in command line. By default, your private data will be used to form a response regardless of it's accuracy (experiment with changing the prompt to change the chat completion behaviour).

