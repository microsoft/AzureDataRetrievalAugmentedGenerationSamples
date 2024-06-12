package azure.cosmos.mongo.vcore.demo;

import dev.langchain4j.data.document.Document;
import dev.langchain4j.data.document.DocumentParser;
import dev.langchain4j.data.document.DocumentSplitter;
import dev.langchain4j.data.document.parser.TextDocumentParser;
import dev.langchain4j.data.document.parser.apache.pdfbox.ApachePdfBoxDocumentParser;
import dev.langchain4j.data.document.splitter.DocumentSplitters;
import dev.langchain4j.data.embedding.Embedding;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.memory.ChatMemory;
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
import dev.langchain4j.model.azure.AzureOpenAiChatModel;
import dev.langchain4j.model.azure.AzureOpenAiEmbeddingModel;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.embedding.EmbeddingModel;
import dev.langchain4j.model.openai.OpenAiTokenizer;
import dev.langchain4j.rag.content.retriever.ContentRetriever;
import dev.langchain4j.rag.content.retriever.EmbeddingStoreContentRetriever;
import dev.langchain4j.service.AiServices;
import dev.langchain4j.service.UserMessage;
import dev.langchain4j.service.V;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.azure.cosmos.mongo.vcore.AzureCosmosDbMongoVCoreEmbeddingStore;


import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.InputStream;
import java.util.*;

import static dev.langchain4j.model.azure.AzureOpenAiModelName.GPT_3_5_TURBO;
import static dev.langchain4j.model.azure.AzureOpenAiModelName.TEXT_EMBEDDING_ADA_002;

public class AzureCosmosDBMongoVCoreLangchainDemo {

    // Azure OpenAI endpoint
    private final static String AZURE_OPENAI_ENDPOINT = System.getenv("AZURE_OPENAI_ENDPOINT");

    // Azure OpenAI API key
    private final static String AZURE_OPENAI_KEY = System.getenv("AZURE_OPENAI_APIKEY");

    // Azure OpenAI Chat model deployment ID
    private final static String CHAT_MODEL_DEPLOYMENT = System.getenv("AZURE_OPENAI_CHATDEPLOYMENTID");

    // Azure OpenAI Embedding model deployment ID
    private final static String EMBEDDINGS_MODEL_DEPLOYMENT = System.getenv("AZURE_OPENAI_EMBEDDINGDEPLOYMENTID");

    // Azure Cosmos DB Mongo vCore connection string
    private final static String MONGODB_CONN_STRING = System.getenv("COSMOS_URI_HNSW");

    // Prompt template for the user message - experiment with different prompts!
    private final static String prompt = "Only use the context information to answer the question" +
            "even if the answer appears incorrect! {{message}}";

    public static void main(String[] args) throws FileNotFoundException {

        // Let's create a customer support agent to chat.
        ChatBotAgent agent = createChatBotAgent();

        // Now, you can ask questions such as
        // - Explain pattern recognition to me.
        // - What are the advantages of using computer vision.?
        // - Give me some different techniques for pattern recognition.

        try (Scanner scanner = new Scanner(System.in)) {
            while (true) {
                System.out.println("==================================================");
                System.out.print("User question: ");
                String userQuery = scanner.nextLine();
                System.out.println("==================================================");

                if ("exit".equalsIgnoreCase(userQuery)) {
                    break;
                }
                String agentAnswer = agent.answer(userQuery);
                System.out.println("==================================================");
                System.out.println("Agent response: ");
                printWrapped(agentAnswer, 80);
            }
        }
    }

    private static ChatBotAgent createChatBotAgent() throws FileNotFoundException {
        // First, let's create a chat model, also known as a LLM, which will answer our queries.
        // In this example, we will use Azure OpenAI's gpt-3.5-turbo, but you can choose any supported model.
        // Langchain4j currently supports more than 10 popular LLM providers.

        ChatLanguageModel model = AzureOpenAiChatModel.builder()
                .endpoint(AZURE_OPENAI_ENDPOINT)
                .apiKey(AZURE_OPENAI_KEY)
                .deploymentName(CHAT_MODEL_DEPLOYMENT)
                .tokenizer(new OpenAiTokenizer(GPT_3_5_TURBO))
                .temperature(0.3)
                .logRequestsAndResponses(true)
                .build();

        System.out.println("Azure Open AI Chat Model initialized");
        // Now, let's load a document that we want to use for RAG.
        // We are using abstracts of papers submitted to Computer Vision and Pattern Recognition Conference
        // in 2019 (CVPR19). We are importing multiple pdf documents.
        // LangChain4j offers built-in support for loading documents from various sources:
        // File System, URL, Amazon S3, Azure Blob Storage, GitHub, Tencent COS.
        // Additionally, LangChain4j supports parsing multiple document types:
        // text, pdf, doc, xls, ppt.
        // However, you can also manually import your data from other sources.
        List<Document> documents = loadDocuments();
        System.out.println("Documents are loaded");


        // Now, we need to split this document into smaller segments, also known as "chunks."
        // This approach allows us to send only relevant segments to the LLM in response to a user query,
        // rather than the entire document. A good starting point is to use a recursive document splitter
        // that initially attempts to split by paragraphs. If a paragraph is too large to fit into a single segment,
        // the splitter will recursively divide it by newlines, then by sentences, and finally by words,
        // if necessary, to ensure each piece of text fits into a single segment.
        DocumentSplitter splitter = DocumentSplitters.recursive(300, 0);
        List<TextSegment> segments = splitter.splitAll(documents);
        System.out.println("Documents are split in chunks");

        // Now, we need to embed (also known as "vectorize") these segments.
        // Embedding is needed for performing similarity searches.
        // For this example, we'll use Azure Open AI text embedding model ada-002, but you can choose any supported model.
        // Langchain4j currently supports more than 10 popular embedding model providers.
        EmbeddingModel embeddingModel = AzureOpenAiEmbeddingModel.builder()
                .endpoint(AZURE_OPENAI_ENDPOINT)
                .apiKey(AZURE_OPENAI_KEY)
                .deploymentName(EMBEDDINGS_MODEL_DEPLOYMENT)
                .tokenizer(new OpenAiTokenizer(TEXT_EMBEDDING_ADA_002))
                .logRequestsAndResponses(true)
                .build();
        System.out.println("Azure Open AI Embedding Model initialized");
        List<Embedding> embeddings = embeddingModel.embedAll(segments).content();
        System.out.println("Document chunks are embedded");

        // Next, we will store these embeddings in an embedding store (also known as a "vector database").
        // This store will be used to search for relevant segments during each interaction with the LLM.
        // We are using the Azure Cosmos DB Mongo vCOre embedding store.
        EmbeddingStore<TextSegment> embeddingStore = AzureCosmosDbMongoVCoreEmbeddingStore.builder()
                .connectionString(MONGODB_CONN_STRING)
                .databaseName("langchain_java-db")
                .collectionName("langchain_java-coll")
                .indexName("test_index")
                .applicationName("JAVA_LANG_CHAIN")
                .createIndex(true)
                .kind("vector-hnsw")
                .numLists(1)
                .dimensions(1536)
                .m(16)
                .efConstruction(64)
                .efSearch(40)
                .build();
        System.out.println("Azure CosmosDB Mongo vCore Embedding Store initialized");
        embeddingStore.addAll(embeddings, segments);
        System.out.println("Vector embeddings and the chunked documents added to the embedding store");

        // The content retriever is responsible for retrieving relevant content based on a user query.
        // Currently, it is capable of retrieving text segments, but future enhancements will include support for
        // additional modalities like images, audio, and more.
        ContentRetriever contentRetriever = EmbeddingStoreContentRetriever.builder()
                .embeddingStore(embeddingStore)
                .embeddingModel(embeddingModel)
                .maxResults(2) // on each interaction we will retrieve the 2 most relevant segments
                .minScore(0.5) // we want to retrieve segments at least somewhat similar to user query
                .build();
        System.out.println("Embedding store is initialized as a retriever");

        // Optionally, we can use a chat memory, enabling back-and-forth conversation with the LLM
        // and allowing it to remember previous interactions.
        // Currently, LangChain4j offers two chat memory implementations:
        // MessageWindowChatMemory and TokenWindowChatMemory.
        ChatMemory chatMemory = MessageWindowChatMemory.withMaxMessages(10);
        System.out.println("Chat Memory is initialized with a max retention size of 10 conversations");

        // The final step is to build our AI Service,
        // configuring it to use the components we've created above.
        System.out.println("Creating an AI service with our chat model, embedding store as a retriever, and chat memory.");
        return AiServices.builder(ChatBotAgent.class)
                .chatLanguageModel(model)
                .contentRetriever(contentRetriever)
                .chatMemory(chatMemory)
                .build();
    }
    private static List<Document> loadDocuments() throws FileNotFoundException {

        // Load all the documents from the PDF_docs directory - you can also add your own documents into this directory
        String workingDirectory = System.getProperty("user.dir");
        String filePath = workingDirectory + "/src/main/java/PDF_docs";
        File folder = new File(filePath);
        List<Document> documentList = new ArrayList<>();
        Stack<File> directoryStack = new Stack<>();
        directoryStack.push(folder);

        while (!directoryStack.isEmpty()) {
            File currentDirectory = directoryStack.pop();
            File[] files = currentDirectory.listFiles();
            if (files != null) {
                DocumentParser textParser = new TextDocumentParser();
                DocumentParser pdfParser = new ApachePdfBoxDocumentParser();
                for (File file : files) {
                    if (file.getName().endsWith("txt")) {
                        InputStream inputStream = new FileInputStream(file);
                        Document document = textParser.parse(inputStream);
                        documentList.add(document);
                    } else if (file.getName().endsWith(".pdf")) {
                        InputStream inputStream = new FileInputStream(file);
                        Document document = pdfParser.parse(inputStream);
                        documentList.add(document);
                    } else if (file.isDirectory()) {
                        directoryStack.push(file);
                    }
                }
            }
        }
        return documentList;
    }

    private static void printWrapped(String str, int lineWidth) {
        StringBuilder sb = new StringBuilder(str.length());
        int length = 0;

        // Split the input string into lines
        String[] lines = str.split("\\R");

        for (String line : lines) {
            // Handle bullet points separately
            if (line.startsWith("•") || line.startsWith("*") || line.startsWith("-")) {
                if (length != 0) {
                    sb.append(System.lineSeparator());
                    length = 0;
                }
                sb.append(line).append(System.lineSeparator());
            } else {
                for (String word : line.split("\\s+")) {
                    if (length + word.length() > lineWidth) {
                        sb.append(System.lineSeparator());
                        length = 0;
                    }
                    sb.append(word).append(" ");
                    length += word.length() + 1;
                }
                sb.append(System.lineSeparator());
                length = 0;
            }
        }

        System.out.println(sb);
    }

    /**
     * This is an "AI Service". It is a Java service with AI capabilities/features.
     * It can be integrated into your code like any other service, acting as a bean, and is even mockable.
     * The goal is to seamlessly integrate AI functionality into your (existing) codebase with minimal friction.
     * It's conceptually similar to Spring Data JPA or Retrofit.
     * You define an interface and optionally customize it with annotations.
     * LangChain4j then provides an implementation for this interface using proxy and reflection.
     * This approach abstracts away all the complexity and boilerplate.
     * So you won't need to juggle the model, messages, memory, RAG components, tools, output parsers, etc.
     * However, don't worry. It's quite flexible and configurable, so you'll be able to tailor it
     * to your specific use case.
     */
    interface ChatBotAgent {
        @UserMessage (prompt)
        String answer(@V("message") String query);

    }

}
