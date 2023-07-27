using Azure;
using Azure.AI.OpenAI;
using Azure.Core;
using Microsoft.Azure.Cosmos;
using System.Text.RegularExpressions;

namespace CosmosRecipeGuide.Services;

/// <summary>
/// Service to access Azure OpenAI.
/// </summary>
public class OpenAIService
{

    private readonly string _openAIEmbeddingDeployment = string.Empty;
    private readonly string _openAICompletionDeployment = string.Empty;
    private readonly int _openAIMaxTokens = default;

    private readonly OpenAIClient? _openAIClient;

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

    public OpenAIService(string endpoint, string key, string embeddingsDeployment, string CompletionDeployment, string maxTokens)
    {
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
            if (endpoint.Contains("api.openai.com"))
                _openAIClient = new OpenAIClient(key, clientOptions);
            else
                _openAIClient = new(new Uri(endpoint), new AzureKeyCredential(key), clientOptions);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"OpenAIService Constructor failure: {ex.Message}");
        }
    }

    public async Task<float[]?> GetEmbeddingsAsync(dynamic data)
    {
        try
        {
            EmbeddingsOptions options = new EmbeddingsOptions(data)
            {
                Input = data
            };

            var response = await _openAIClient.GetEmbeddingsAsync(_openAIEmbeddingDeployment, options);

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

}